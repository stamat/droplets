/**
 * Droplet manager front-end.
 *
 * The library grid and the detail view are both rendered from what
 * system/manager/main.py returns; the settings form is generated from the
 * `options` schema each droplet's own manifest declares, so the manager never
 * needs to know what a given widget is configurable for.
 */

/* ---- bridge ------------------------------------------------------------ *
 * droplets.recieve is a single global callback, so replies can only be told
 * apart by order: one request is in flight at a time and the queue head owns
 * whatever comes back.                                                      */

var queue = [];
var busy = false;

function call(method, args) {
	return new Promise(function (resolve) {
		queue.push({ method: method, args: args || {}, resolve: resolve });
		pump();
	});
}

function pump() {
	if (busy || !queue.length) return;
	busy = true;
	droplets.send(JSON.stringify({ method: queue[0].method, args: queue[0].args }));
}

droplets.recieve = function (result) {
	var job = queue.shift();
	busy = false;
	if (job) job.resolve(result);
	pump();
};

/* ---- helpers ----------------------------------------------------------- */

function el(id) { return document.getElementById(id); }

function make(tag, attrs, text) {
	var node = document.createElement(tag);
	for (var key in attrs || {}) {
		if (attrs[key] !== null && attrs[key] !== undefined) node.setAttribute(key, attrs[key]);
	}
	if (text !== undefined && text !== null) node.textContent = text;
	return node;
}

// A 1x1 transparent GIF: droplets that ship no icon still get a tile of the
// same size, so the grid keeps its rhythm.
var BLANK = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';

function badges(droplet) {
	return [droplet.type, droplet.origin].filter(Boolean);
}

/* ---- library ----------------------------------------------------------- */

var library = [];
var current = null;   // name of the droplet open in the detail view, or null

function render(list) {
	library = list;
	var grid = el('library');
	grid.textContent = '';
	list.forEach(function (droplet) {
		grid.appendChild(droplet.error ? brokenCard(droplet) : card(droplet));
	});
	el('count').textContent = list.length + (list.length === 1 ? ' droplet' : ' droplets');
}

function brokenCard(droplet) {
	var node = make('article', { class: 'card broken' });
	node.appendChild(make('h2', null, droplet.title));
	node.appendChild(make('p', { class: 'error' }, droplet.error));
	return node;
}

function card(droplet) {
	var node = make('article', { class: 'card' + (droplet.running ? ' on' : '') });

	var open = make('button', { type: 'button', class: 'open' });
	open.appendChild(make('img', { class: 'icon', src: droplet.icon || BLANK, alt: '' }));
	var text = make('div', { class: 'card-text' });
	text.appendChild(make('h2', null, droplet.title));
	text.appendChild(make('p', { class: 'muted' }, droplet.description || ''));
	var tags = make('p', { class: 'badges' });
	badges(droplet).forEach(function (b) { tags.appendChild(make('span', { class: 'badge' }, b)); });
	text.appendChild(tags);
	open.appendChild(text);
	open.addEventListener('click', function () { openDetail(droplet.name); });
	node.appendChild(open);

	node.appendChild(toggle(droplet, function (running) {
		node.className = 'card' + (running ? ' on' : '');
	}));
	return node;
}

function toggle(droplet, done) {
	var label = make('label', { class: 'switch' });
	var input = make('input', { type: 'checkbox' });
	input.checked = droplet.running;
	input.addEventListener('change', function () {
		var wanted = input.checked;
		input.disabled = true;
		call('set_enabled', { name: droplet.name, enabled: wanted }).then(function (state) {
			input.disabled = false;
			droplet.running = state.running;
			droplet.enabled = wanted;
			input.checked = state.running;
			if (done) done(state.running);
		});
	});
	label.appendChild(input);
	label.appendChild(make('span', { class: 'slider' }));
	return label;
}

/* ---- detail ------------------------------------------------------------ */

function find(name) {
	return library.filter(function (d) { return d.name === name; })[0];
}

function openDetail(name) {
	var droplet = find(name);
	if (!droplet) return;
	current = name;

	el('detail-icon').src = droplet.icon || BLANK;
	el('detail-title').textContent = droplet.title;
	el('detail-description').textContent = droplet.description || '';
	var tags = el('detail-badges');
	tags.textContent = '';
	badges(droplet).forEach(function (b) { tags.appendChild(make('span', { class: 'badge' }, b)); });

	var check = el('detail-toggle');
	check.checked = droplet.running;
	check.onchange = function () {
		var wanted = check.checked;
		check.disabled = true;
		call('set_enabled', { name: droplet.name, enabled: wanted }).then(function (state) {
			check.disabled = false;
			droplet.running = state.running;
			droplet.enabled = wanted;
			check.checked = state.running;
		});
	};

	renderOptions(droplet);

	var shots = el('shots');
	shots.textContent = '';
	shots.hidden = !droplet.has_screenshots;
	if (droplet.has_screenshots) {
		call('screenshots', { name: name }).then(function (uris) {
			if (current !== name) return;   // user moved on while we were reading
			uris.forEach(function (uri) { shots.appendChild(make('img', { src: uri, alt: '' })); });
		});
	}

	el('library').hidden = true;
	el('detail').hidden = false;
	el('back').hidden = false;
	// Heading stays "Droplets": the back button next to it returns to the list,
	// so it labels the destination, not the open droplet.
	el('count').textContent = '';
}

function closeDetail() {
	current = null;
	el('detail').hidden = true;
	el('back').hidden = true;
	el('library').hidden = false;
	el('heading').textContent = 'Droplets';
	refresh();
}

/* ---- settings form ----------------------------------------------------- */

/**
 * Build one input per option the manifest declares. Geometry is deliberately
 * absent: position and size are written by the running window itself, and the
 * manifest loader refuses an option that tries to claim one of those names.
 */
function renderOptions(droplet) {
	var form = el('options');
	form.textContent = '';
	el('saved').textContent = '';
	var names = Object.keys(droplet.options || {});
	el('settings').hidden = !names.length;
	if (!names.length) return;

	names.forEach(function (name) {
		var spec = droplet.options[name];
		var value = droplet.values[name];
		var row = make('div', { class: 'field' });
		var input = inputFor(name, spec, value);
		var label = make('label', { for: 'opt-' + name }, spec.label || name);

		if (spec.type === 'bool') {
			row.className = 'field inline';
			row.appendChild(input);
			row.appendChild(label);
		} else {
			row.appendChild(label);
			row.appendChild(input);
		}
		if (spec.description) row.appendChild(make('p', { class: 'muted hint' }, spec.description));
		form.appendChild(row);
	});
}

function inputFor(name, spec, value) {
	var id = 'opt-' + name;
	if (spec.type === 'enum') {
		var select = make('select', { id: id, 'data-option': name });
		(spec.choices || []).forEach(function (choice) {
			var option = make('option', { value: choice }, choice);
			if (choice === value) option.selected = true;
			select.appendChild(option);
		});
		return select;
	}
	if (spec.type === 'bool') {
		var check = make('input', { type: 'checkbox', id: id, 'data-option': name });
		check.checked = !!value;
		return check;
	}
	if (spec.type === 'int' || spec.type === 'number') {
		var number = make('input', {
			type: 'number', id: id, 'data-option': name,
			step: spec.type === 'int' ? 1 : 'any',
			min: spec.min, max: spec.max
		});
		number.value = value === null || value === undefined ? '' : value;
		return number;
	}
	var text = make('input', { type: 'text', id: id, 'data-option': name });
	text.value = value === null || value === undefined ? '' : value;
	return text;
}

/** Read the form back into the JSON types the manifest declared. */
function collectOptions(droplet) {
	var values = {};
	Array.prototype.forEach.call(el('options').querySelectorAll('[data-option]'), function (node) {
		var name = node.getAttribute('data-option');
		var type = droplet.options[name].type;
		if (type === 'bool') values[name] = node.checked;
		else if (type === 'int') values[name] = parseInt(node.value, 10);
		else if (type === 'number') values[name] = parseFloat(node.value);
		else values[name] = node.value;
	});
	return values;
}

function save() {
	var droplet = find(current);
	if (!droplet) return;
	var note = el('saved');
	note.textContent = '';
	note.className = 'muted';
	call('set_options', { name: droplet.name, values: collectOptions(droplet) }).then(function (result) {
		if (result.ok) {
			droplet.values = result.values;
			note.textContent = 'Saved';
		} else {
			note.textContent = result.error;
			note.className = 'error';
		}
	});
}

/* ---- boot -------------------------------------------------------------- */

function refresh() {
	return call('droplets', {}).then(function (list) {
		if (current === null) {
			render(list);
			return;
		}
		library = list;
		var droplet = find(current);
		if (!droplet) return closeDetail();   // droplet disappeared from apps/
		// Don't stomp a toggle mid-request (its own resolve will set the truth).
		var check = el('detail-toggle');
		if (!check.disabled) check.checked = droplet.running;
	});
}

el('back').addEventListener('click', closeDetail);
el('save').addEventListener('click', save);

// Bring back the droplets that were on last session, then show the library.
// autostart is a no-op for anything already running, so the poll below stays
// the single source of on/off truth.
call('autostart', {}).then(refresh);
// A droplet runs as its own process and can be closed from its own context
// menu (or crash), with no signal back to the manager. So the on/off state is
// re-read on a short poll -- in both the list and the open detail view -- and
// the switch follows whatever is actually running.
setInterval(refresh, 2000);
