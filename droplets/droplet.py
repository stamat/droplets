import os,sys
# This needs pygtk 2.9 installed.
sys.path[:0] = ['/usr/local/lib/python2.4/site-packages/gtk-2.0']
import gtk,gobject,pygtk,webkit,cairo
pygtk.require('2.0')
import json
import urllib
from manifest import Manifest

if gtk.pygtk_version < (2,9,0):
    print "PyGtk 2.9.0 or later required"
    raise SystemExit

class Droplet:
	window = None
	browser = None
	manifest = None
	module = None
	path = None
	temp = {'x':0, 'y':0}
	
	
	##
	# Function that makes a gtk.Widget transparent through
	# gtk.Widget.set_colormap. Used in {@link #prepare prepare method}
	#
	# @param 	widget	gtk.Widget object
	# @return 	bool	success
	def make_transparent(self, widget):
		screen = widget.get_screen()
		colormap = screen.get_rgba_colormap()
		if colormap != None:
			widget.set_colormap(colormap)
			return True
		else:
			return False
			
	#TODO: FALLBACK OLD SCHOOL!!! get background, paint it on the window
	
#	def transparent_oldschool(self, widget):
#		cr = widget.cairo_create()
#		cr.set_operator(cairo.OPERATOR_CLEAR)
#		region = gtk.gdk.region_rectangle(0, 0, self.manifest.width, self.manifest.height)
#		cr.region(region)
#		cr.fill()
#		return False
	


	##
	# On main droplet window 'configure-event', store current 
	# X, Y coordinates. Binded in {@link #prepare prepare method}
	# 
	# @param	w	gtk.Window object
	# @param	e	gtk.gdk.Event object
	def on_configure(self,w, e):
		self.temp['x'] = e.x
		self.temp['y'] = e.y


	##
	# On main droplet window 'focus-out-event', write coordinates 
	# to manifest file. Binded in {@link #prepare prepare method}
	# 
	# @param	w	gtk.Window object
	# @param	e	gtk.gdk.Event object	
	def on_focus_out(self, w=None, e=None):
		if self.manifest.x != self.temp['x'] or self.manifest.y != self.temp['y']:
			self.manifest.set('x', self.temp['x'])
			self.manifest.set('y', self.temp['y'])
			self.manifest.dump_manifest(self.manifest.path)

	##
	# On webkit.WebView 'title-changed' event, recieve and parse
	# JSON from title and call a corespondant fuction from imported 
	# executable. It sends back the result at the end.
	# Can call some predefined functions od this module that start with "droplet_"
	# Binded in {@link #prepare prepare method}
	#
	# JSON message format:
	#	{
	#		"method": "<function name>",
	#		"args": {
	#			"<argument name>": <argument value>
	#			}
	#	}
	# 
	# @param	msg		serialized JSON
	def recieve(self, msg):
		if msg != 'null':
			#TODO try and catch all data passed by other developers
			packet = json.loads(msg)
			if packet['method'].startswith('droplet_'):
				#### TODO: NOT SURE IF SAFE!?
				fn = getattr(self, packet['method'])
			else:
				fn = getattr(self.module, packet['method'])
				#### TODO: NOT SURE IF SAFE!?
				if self.dict_key_exists(packet['args'], 'gtk'):
					packet['args']['gtk'] = gtk
				if self.dict_key_exists(packet['args'], 'browser'):
					packet['args']['browser'] = browser
				if self.dict_key_exists(packet['args'], 'window'):
					packet['args']['window'] = window 
			if fn:
				result = fn(**packet['args'])
				self.send(result)
	
	#TODO: MINIMIZE, MAXIMIZE, Reload, get position, get size, Open Settings... and such
	def droplet_connect(self, object, event, callback):
		obj = getattr(self, object)
		obj.connect(event, self.event_to_json, callback)

	def droplet_drag(self, button, x, y, time):
		self.window.begin_move_drag(button, x, y, time)
		
	def droplet_move(self, x, y):
		self.window.move(x, y)
	
	def droplet_deactivate(self, w=None, e=None):
		self.on_focus_out()
		gtk.main_quit()
		raise SystemExit	

	def dict_key_exists(self, dict, key):
		if key in dict:
			return True
		return False
	
	def send(self, msg):
		self.browser.execute_script('droplets.recieve("'+str(msg)+'");')
	
	def prepare_widget(self, manifest, module):
		window = gtk.Window()
	
		window.set_app_paintable(True)
	
		window.set_keep_below(manifest.below)
		window.set_keep_above(manifest.above)
		window.set_skip_taskbar_hint(manifest.skip_taskbar)
		window.set_skip_pager_hint(manifest.skip_pager)
		window.set_decorated(manifest.decorated)
		
		if manifest.transparent:
			self.make_transparent(window)
		
		window.set_title(manifest.title)
		
		if manifest.stick:
			window.stick()
		
		if manifest.icon != None:
			window.set_icon_from_file (path+manifest['icon'])
		
		window.connect('configure-event', self.on_configure)
		window.connect('focus-out-event', self.on_focus_out)
		#TODO: on destroy
		window.connect('destroy', self.droplet_deactivate)
		
		browser = webkit.WebView()
		browser.set_transparent(manifest.transparent)
		browser.props.settings.props.enable_default_context_menu = manifest.default_context_menu
		browser.execute_script("var droplets = {}; droplets.send = function(command) { document.title = 'null'; if(command != undefined) document.title = command;}")
	
		if not module == None:
			def on_title_change_wrapper(w, e, title): self.recieve(title)
			browser.connect('title-changed', on_title_change_wrapper)
	
		if manifest.drag:
			def drag_wrapper(w, e): 
				if e.button == 1:
					self.droplet_drag(e.button, e.x_root, e.y_root, e.time)
			browser.connect('button-press-event', drag_wrapper)
	
		
		window.add(browser)
			
		window.resize(manifest.width, manifest.height)
			
		if not manifest.hidden:
			window.show_all()
			
		if manifest.x != None and manifest.y != None:
			window.move(manifest.x , manifest.y)
			
		def on_load_wrapper(w,e): window.set_opacity(manifest.opacity)
		browser.connect('load-finished', on_load_wrapper)
	
		return window, browser
	
	#### TODO: NOT SURE IF SAFE!?
	def event_to_json(self, w, e, f):
		dict = self.attrs_to_dict(e)
		dict['type'] = e.type.value_name
		self.browser.execute_script(f+"""('"""+str(json.dumps(dict))+"""');""")
	
	def attrs_to_dict(self, obj):
		attribs = dir(obj)
		result = {}
		for v in attribs:
			attr = getattr(obj,v)
			t = type(attr)
			if t is str or t is int or t is bool or t is float:
				result[v] = attr
	
		return result
	
	def load_widget(self, browser, origin, source):
		if origin == 'local':
			file = os.path.abspath(source)
			source = 'file://' + urllib.pathname2url(file)
			browser.load_uri(source)
	
	def import_from_uri(self, path, executable):
		try:
			splited_path = path[:-1].split('/')
			current_path = ''
			module_path = ''
		
			for v in splited_path:
				module_path += v + '.'
				current_path += v + '/'
				if not os.path.exists(current_path+'__init__.py'):
					f = open(current_path+'__init__.py', 'w+')
					f.close()
		
			module = __import__(module_path+executable, fromlist=[module_path[:-1]])
		except ImportError:
			module = None
	
		return module
			
	def init_widget(self, path, custom_manifest = None):
		manifest_file = 'manifest.json' #XXX: lol
	
		if path[len(path)-1] != '/':
			path = path + '/'
	
		manifest = Manifest(path+manifest_file)
		self.temp['x'] = manifest.x
		self.temp['y'] = manifest.y
		#TODO: If executable ends with .py? remove py!
		module = self.import_from_uri(path, manifest.executable)
		window,browser = self.prepare_widget(manifest, module)
		#TODO: Check if the file is local file!
		self.load_widget(browser, manifest.origin, path+manifest.source)
	
		return manifest, module, window, browser
		
	def __init__(self, path, custom_manifest = None):
		self.manifest,self.module,self.window,self.browser = self.init_widget(path, custom_manifest)
