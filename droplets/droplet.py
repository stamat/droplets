import os,sys
# This needs pygtk 2.9 installed.
#sys.path[:0] = ['/usr/local/lib/python2.4/site-packages/gtk-2.0']
import gtk
import gobject
import pygtk
import webkit
import cairo
pygtk.require('2.0')
import json
import urllib
import os
import imp
import re
import math
from subprocess import call
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
	drag_handler_id = None
	root_url = None
	
	##
	# Imports module by given uri using imp module used to implement import
	#
	# @param 	uri 	Uri of the module
	# @param	absl	Is uri absolute
	# @return	module	Python module
	def importFromURI(self, uri, absl=False):
		if not absl:
			uri = os.path.normpath(os.path.join(os.path.dirname(__file__), uri))
		path, fname = os.path.split(uri)
		mname, ext = os.path.splitext(fname)
		
	 	no_ext = os.path.join(path,mname)
	 	
		if os.path.exists(no_ext + '.pyc'):
			try:
				return imp.load_compiled(mname, no_ext + '.pyc')
			except:
				pass
		if os.path.exists(no_ext + '.py'):
			try:
				return imp.load_source(mname, no_ext + '.py')
			except:
				pass
	
	# prepares bitmap so cairo can draw on it
	def prepareBitmap(self, w, h):
		bitmap = gtk.gdk.Pixmap(None, w, h, 1)
		
		# Clear the bitmap
		fg = gtk.gdk.Color(pixel=0)
		bg = gtk.gdk.Color(pixel=-1)
		fg_gc = bitmap.new_gc(foreground=fg, background=bg)
		bitmap.draw_rectangle(fg_gc, True, 0, 0, w, h)
		
		return bitmap
	
	# A simple demonstration of using cairo to shape windows.
	# Natan 'whatah' Zohar
	
	# Shape the window into a rounded rectangle
	def reshaperect(self, obj, allocation, radius=0):
		bitmap = self.prepareBitmap(allocation.width, allocation.height)
		
		# Draw our shape into the pixmap using cairo
		# Let's try drawing a rectangle with rounded edges.
		padding = 0 # Padding from the edges of the window
		rounded = radius # How round to make the edges
		cr = bitmap.cairo_create()
		cr.set_source_rgb(0,0,0)
		# Move to top corner
		cr.move_to(0+padding+rounded, 0+padding)

		# Top right corner and round the edge
		cr.line_to(w-padding-rounded, 0+padding)
		cr.arc(w-padding-rounded, 0+padding+rounded, rounded, math.pi/2, 0)

		# Bottom right corner and round the edge
		cr.line_to(w-padding, h-padding-rounded)
		cr.arc(w-padding-rounded, h-padding-rounded, rounded, 0, math.pi/2)

		# Bottom left corner and round the edge.
		cr.line_to(0+padding+rounded, h-padding)
		cr.arc(0+padding+rounded, h-padding-rounded, rounded, math.pi+math.pi/2, math.pi)

		# Top left corner and round the edge
		cr.line_to(0+padding, 0+padding+rounded)
		cr.arc(0+padding+rounded, 0+padding+rounded, rounded, math.pi/2, 0)

		# Fill in the shape.
		cr.fill()

		# Set the window shape
		obj.shape_combine_mask(bitmap, 0, 0)
		obj.show()


    # Reshape the window into a circle
	def reshapecircle(self, obj, allocation):
		bitmap = self.prepareBitmap(allocation.width, allocation.height)
		
		# Draw our shape into the bitmap using cairo      
		cr = bitmap.cairo_create()
		cr.set_source_rgb(0,0,0)
		cr.arc(w/2,h/2,min(h,w)/2,0,2*math.pi)
		cr.fill()

		# Set the window shape
		obj.shape_combine_mask(bitmap, 0, 0)
		obj.show()
	
	#TODO:
	def reshapemask(self, obj, allocation, mask):
		bitmap = self.prepareBitmap(allocation.width, allocation.height)
		
		bitmap.draw_pixbuf(None, gtk.gdk.pixbuf_new_from_file(mask), 0, 0, 0, 0)
		
		obj.shape_combine_mask(bitmap, 0, 0)
		obj.show()
		
		
	##
	# Function that makes a gtk.Widget transparent through
	# gtk.Widget.set_colormap. Used in {@link #prepare prepare method}
	#
	# @param 	widget	gtk.Widget object
	# @return 	bool	success
	def transparent_window (self, widget):
		screen = widget.get_screen()
		colormap = screen.get_rgba_colormap()
		if colormap != None:
			widget.set_colormap(colormap)
			return True
		else:
			return False
	
	#from pygtk documentation
	def transparent_expose (self, widget, event):
		cr = widget.window.cairo_create()
		cr.set_operator(cairo.OPERATOR_CLEAR)

		region = gtk.gdk.region_rectangle(event.area)
		cr.region(region)
		cr.fill()
		
		return False
	##
	# LOL!
	def dict_key_exists(self, dict, key):
		return key in dict
		
		
	##
	# On main droplet window 'configure-event', store current 
	# X, Y coordinates. Binded in {@link #prepare prepare method}
	# 
	# @param	w	gtk.Window object
	# @param	e	gtk.gdk.Event object
	def on_configure(self, w, e):
		self.temp['x'], self.temp['y'] = w.get_position()


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
	# @param	msg		 JSON string
	def recieve(self, msg):
		if msg != 'null' and self.manifest.origin == 'local':
			#TODO TRY AND CATCH all data passed by other developers
			packet = json.loads(msg)
			if packet['method'].startswith('droplet_'):
				fn = getattr(self, packet['method'])
			else:
				fn = getattr(self.module, packet['method'])
				
				if self.dict_key_exists(packet['args'], 'gtk'):
					packet['args']['gtk'] = gtk
				if self.dict_key_exists(packet['args'], 'browser'):
					packet['args']['browser'] = browser
				if self.dict_key_exists(packet['args'], 'window'):
					packet['args']['window'] = window 
			if fn:
				result = fn(**packet['args'])
				self.send(result)
				
	##
	# Convers a gtk events and DND gtk events to JSON to enable the connection from JavaScript
	def event_to_json(self, w, *args):
		dict = {}
		#on gtk event
		if(isinstance(args[0], gtk.gdk.Event)):
			dict = self.attrs_to_dict(args[0])
			dict['type'] = args[0].type.value_name
		elif(isinstance(args[0], gtk.gdk.DragContext)): #on drag context, what is the point of this lol... but let it stay, i was tired and stupid
			print args[0].drag_get_selection()
			dict = {
				'targets': args[0].targets,
				'uris': args[3].get_uris(),
				'x': args[1],
				'y': args[2],
				'text': args[3].get_text()
			}
		self.browser.execute_script(args[len(args)-1]+"""('"""+str(json.dumps(dict))+"""');""")
	
	
	def attrs_to_dict(self, obj):
		attribs = dir(obj)
		result = {}
		for v in attribs:
			attr = getattr(obj,v)
			t = type(attr)
			if t is str or t is int or t is bool or t is float:
				result[v] = attr
	
		return result
	
	
	def send(self, msg):
		self.browser.execute_script('droplets.recieve("'+str(msg)+'");')
	
	#TODO: MINIMIZE, MAXIMIZE, Reload, get position, get size, Open Settings... and such
	def droplet_connect(self, object, event, callback):
		obj = getattr(self, object)
		obj.connect(event, self.event_to_json, callback)

	def droplet_drag(self, button, x, y, time):
		self.window.begin_move_drag(button, int(x), int(y), time)
	
	def drag_event_wrapper(self, w, e): 
		if e.button == 1:
			self.droplet_drag(e.button, e.x_root, e.y_root, e.time)
	
	def droplet_move_enable(self, browser=None, manifest=None):
		if browser is None: browser = self.browser
		if manifest is None: manifest = self.manifest
		self.drag_handler_id = browser.connect('button-press-event', self.drag_event_wrapper)
		manifest.drag = True
	
	def droplet_move_disable(self, browser=None, manifest=None):
		if browser is None: browser = self.browser
		if manifest is None: manifest = self.manifest
		browser.disconnect(self.drag_handler_id)
		manifest.drag = False
	
	def droplet_move(self, x, y):
		self.window.move(int(x), int(y))
	
	def droplet_deactivate(self, w=None, e=None):
		self.on_focus_out()
		gtk.main_quit()
		raise SystemExit	
	
	def set_to_transparent(self):
		self.transparent_window(self.window)
		self.browser.set_transparent(True) #set the webview transparency (no background on body)
		self.browser.connect('expose-event', self.transparent_expose)
	
	def toggleProperty(self, w, e):
		label = w.get_label()
		parsed = re.match('^(?P<pref>.*:\s*)(?P<state>.*)$', label)
		state = parsed.group('state').lower()
		pref = parsed.group('pref')
		action = re.match('^\s*(?P<action>[a-zA-Z]*)\s*:\s*$', pref).group('action').lower()

		if state == 'off':
			fn = getattr(self, 'droplet_'+action+'_disable')
			w.set_label(pref+'On')
		elif state == 'on':
			fn = getattr(self, 'droplet_'+action+'_enable')
			w.set_label(pref+'Off')
		fn()
	
	def widgetContextMenu(self):
		#TODO: ONLY ON WIDGETS!!! toggle bool in manifest
		menu = gtk.Menu()
		properties_menu = gtk.Menu()
		remove_menu = gtk.Menu()
		
		def detachFn(*args):
			print args
		menu.attach_to_widget(self.browser, detachFn) ##TODO: see what a fuckin' detach function is
	
		move = gtk.MenuItem("Move: Off")
		stick = gtk.MenuItem("Stick: Off")
		bottom = gtk.MenuItem("Bottom: Off")
		above = gtk.MenuItem("Above: Off")
		properties = gtk.MenuItem("Properties")
		properties.set_submenu(properties_menu)
		settings = gtk.MenuItem("Settings")
	
		remove_submenu = gtk.MenuItem("Deactivate")
		remove_submenu.set_submenu(remove_menu)
		remove = gtk.MenuItem("X")
		remove_menu.append(remove);
	
		properties_menu.append(move)
		properties_menu.append(stick)
		properties_menu.append(bottom)
		properties_menu.append(above)
		menu.append(properties)
		menu.append(settings)
		menu.append(remove_submenu)
		move.show()
		stick.show()
		bottom.show()
		above.show()
		properties.show()
		properties_menu.show()
		settings.show()
		remove.show()
		remove_submenu.show()
	
		move.connect('button-press-event', self.toggleProperty)
		remove.connect('button-press-event', self.droplet_deactivate)
	
		#XXX Watch it... self, widget, event, menu
		def _on_button_press_event(self, event, menu):
			if event.button == 3:
				menu.popup(None, None, None, 0, event.time)
				pass
	
		self.browser.connect('button_press_event',_on_button_press_event, menu)
	
	
	##
	# Window prepare and embed webview
	def prepare_widget(self, manifest, module, path):
		
		window = gtk.Window()
		self.window = window
		browser = webkit.WebView()
		self.browser = browser
		self.manifest = manifest
		self.module = module
		
		
		window.set_resizable(manifest.resizable)
		window.set_keep_below(manifest.below)
		window.set_keep_above(manifest.above)
		window.set_skip_taskbar_hint(manifest.skip_taskbar)
		window.set_skip_pager_hint(manifest.skip_pager)
		window.set_decorated(manifest.decorated)		

		if manifest.transparent:
			self.set_to_transparent()

		if manifest.title != None:
			window.set_title(manifest.title)

		if manifest.stick:
			window.stick()
		
		if manifest.icon != None:
			window.set_icon_from_file (path + manifest.icon)
		
		if manifest.drag:
			self.droplet_move_enable(browser, manifest)
		
		window.connect('configure-event', self.on_configure)
		window.connect('focus-out-event', self.on_focus_out)
		#TODO: on destroy
		window.connect('destroy', self.droplet_deactivate)
		
		
		#set browsers settings
		browser_settings = browser.get_settings()
		
		#XXX: Should it be always false?
		browser_settings.set_property('enable-default-context-menu', manifest.default_context_menu)
		browser_settings.set_property('enable-webaudio', 1)
		browser_settings.set_property('enable-webgl', 1)
		browser_settings.set_property('default-encoding', 'utf8')
		browser_settings.set_property('enable-accelerated-compositing', 1)
		
		if manifest.origin == 'local':	
			browser_settings.set_property('enable-universal-access-from-file-uris', 1)
		browser_settings.set_property('enable-plugins', 0)
		browser_settings.set_property('enable-page-cache', 1)
		

		if manifest.origin == 'local': 
			browser.execute_script("var droplets = {}; droplets.send = function(command) { document.title = 'null'; if(command != undefined) document.title = command;}")
			
			#Enable communication over title changed
			if module != None:
				def on_title_change_wrapper(w, e, title): self.recieve(title)
				browser.connect('title-changed', on_title_change_wrapper)
				
				
		self.widgetContextMenu()
		
		#TODO: Widgets can be either completely local or completely remote in a sense of resources. A web widget cannot have a communication with the system, a local widget cannot have a communication to the web through HTTP, only through python interface, thus disabling a chance that it can accidentaly load malicius scripts that can be changed by the third party
		# Web widgets have alerts and popups blocked completely.
		# In every local python script there will be enabled a function for curl requests and responses and a way to store data
		def redirectNavigLocal (web_view, frame, request, navigation_action, policy_decision):
			
			reason = re.match('^WEBKIT_WEB_NAVIGATION_REASON_(?P<reason>[A-Z0-9_]*)$', navigation_action.get_reason().value_name).group('reason')
			uri = request.get_uri()
			
			if not uri.startswith('file://'):
				policy_decision.ignore()
				return True
			
			if reason == 'OTHER' and self.root_url == None:
				self.root_url = '/'.join(uri.split('/')[:-1])
				policy_decision.use()
				return True
			
			if not uri.startswith(self.root_url):
				policy_decision.ignore()
				call(["xdg-open", uri])
				return True
		
		if manifest.origin =='local': browser.connect('navigation-policy-decision-requested', redirectNavigLocal)
		
		def redirectNavigRemote (web_view, frame, request, navigation_action, policy_decision):
			reason = re.match('^WEBKIT_WEB_NAVIGATION_REASON_(?P<reason>[A-Z0-9_]*)$', navigation_action.get_reason().value_name).group('reason')
			uri = request.get_uri()
			
			if reason == 'OTHER' and self.root_url == None:
				self.root_url = '/'.join(uri.split('/')[:-1])
				policy_decision.use()
				return True
			
			if not uri.startswith(self.root_url):
				policy_decision.ignore()
				return True
				
		
		if manifest.origin =='remote' or manifest.origin == 'hosted': browser.connect('navigation-policy-decision-requested', redirectNavigRemote)
		
		def banRemoteRequests (web_view, frame, web_resource, request, response):
			if not request.get_uri().startswith('file://'):
				request.set_uri('about:blank')
				
		if manifest.origin == 'local': browser.connect('resource-request-starting', banRemoteRequests)
		
		#Ban other mime type to be loaded into the webview, only text/html is allowed
		def banOtherMime (web_view, frame, request, mimetype, policy_decision):
			if mimetype != 'text/html':
				policy_decision.ignore()
				return True
			
		browser.connect('mime-type-policy-decision-requested', banOtherMime)
		
		props = browser.get_window_features()
		print props.get_property('scrollbar-visible')
		
		#add a browser to window
		child = browser
		if manifest.type == 'app':
			child = gtk.ScrolledWindow()
			child.add(browser)
		
		window.add(child)
		
		#set viewport size	
		window.resize(manifest.width, manifest.height)
		
		
		#set window shape if defined
		if manifest.shape == 'roundedrect':
			window.connect('size-allocate', self.reshaperect, manifest.corner_radius)
		if manifest.shape == 'circle':
			window.connect('size-allocate', self.reshapecircle)
		
		if manifest.shape == 'mask':
			window.connect('size-allocate', self.reshapemask, manifest.shape_mask)
		
		if not manifest.hidden:
			window.show_all()
		
		if manifest.x != None and manifest.y != None:
			window.move(manifest.x , manifest.y)
		
		#set window opacity on webview load
		def on_load_wrapper(w,e): window.set_opacity(manifest.opacity)
		browser.connect('load-finished', on_load_wrapper)
		
	
		return window, browser
		
	
	
	
	def load_widget(self, browser, origin, source):
		if origin != 'hosted':
			file = os.path.abspath(source)
			source = 'file://' + urllib.pathname2url(file)
		browser.load_uri(source)
	
			
	def init_widget(self, path, custom_manifest = None):
		manifest_file = 'manifest.json' #XXX: lol
	
		if path[len(path)-1] != '/':
			path = path + '/'
			
		path_to_manifest = None
		if custom_manifest is not None:
			path_to_manifest = custom_manifest
		else:
			path_to_manifest = path+manifest_file
			
		manifest = Manifest(path_to_manifest)
		self.temp['x'] = manifest.x
		self.temp['y'] = manifest.y
		module = self.importFromURI(os.path.join(path, manifest.executable), True)
		window,browser = self.prepare_widget(manifest, module, path)
		
		self.load_widget(browser, manifest.origin, path+manifest.source)
	
		return manifest, module, window, browser
	
		
	def __init__(self, path, custom_manifest = None):
		 self.init_widget(path, custom_manifest)
		 gtk.main()
		 
