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
	
	
	##
	# Function that makes a gtk.Widget transparent through
	# gtk.Widget.set_colormap. Used in {@link #prepare prepare method}
	#
	# @param 	widget	gtk.Widget object
	# @return 	bool	success
	def make_transparent (self, widget):
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
	# On main droplet window 'configure-event', store current 
	# X, Y coordinates. Binded in {@link #prepare prepare method}
	# 
	# @param	w	gtk.Window object
	# @param	e	gtk.gdk.Event object
	def on_configure(self,w, e):
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
	
	#TODO: MINIMIZE, MAXIMIZE, Reload, get position, get size, Open Settings... and such
	def droplet_connect(self, object, event, callback):
		obj = getattr(self, object)
		obj.connect(event, self.event_to_json, callback)

	def droplet_drag(self, button, x, y, time):
		self.window.begin_move_drag(button, int(x), int(y), time)
	
	def drag_event_wrapper(self, w, e): 
		if e.button == 1:
			self.droplet_drag(e.button, e.x_root, e.y_root, e.time)
	
	def droplet_drag_enable(self, browser=None, manifest=None):
		if browser is None: browser = self.browser
		if manifest is None: manifest = self.manifest
		self.drag_handler_id = browser.connect('button-press-event', self.drag_event_wrapper)
		manifest.drag = True
	
	def droplet_drag_disable(self, browser=None, manifest=None):
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

	def dict_key_exists(self, dict, key):
		return key in dict
	
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

		#window.connect('expose-event', self.transparent_expose)		

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
		
		settings = browser.get_settings()
		
		#XXX: Should it be always false?
		settings.set_property('enable-default-context-menu', manifest.default_context_menu)
		settings.set_property('enable-webaudio', 1)
		settings.set_property('enable-webgl', 1)
		settings.set_property('default-encoding', 'utf8')
		settings.set_property('enable-accelerated-compositing', 1)
		if manifest.origin == 'local':	
			settings.set_property('enable-universal-access-from-file-uris', 1)
		settings.set_property('enable-plugins', 0)
		settings.set_property('enable-page-cache', 1)

		#print browser.can_go_back_or_forward()

		if manifest.origin == 'local': browser.execute_script("var droplets = {}; droplets.send = function(command) { document.title = 'null'; if(command != undefined) document.title = command;}")
		browser.connect('expose-event', self.transparent_expose)

		if module != None and manifest.origin == 'local':
			def on_title_change_wrapper(w, e, title): self.recieve(title)
			browser.connect('title-changed', on_title_change_wrapper)
		
		if manifest.drag:
			self.droplet_drag_enable(browser, manifest)
		
		
		
		#TODO: Widgets can be either completely local or completely remote in a sense of resources. A web widget cannot have a communication with the system, a local widget cannot have a communication to the web through HTTP, only through python interface, thus disabling a chance that it can accidentaly load malicius scripts that can be changed by the third party
		# Web widgets have alerts and popups blocked completely.
		# In every local python script there will be enabled a function for curl requests and responses and a way to store data
		def banRemoteNavig (web_view, frame, request, navigation_action, policy_decision):
			if not request.get_uri().startswith('file://'):
				policy_decision.ignore()
				return True
		
		if manifest.origin == 'local': browser.connect('navigation-policy-decision-requested', banRemoteNavig)
		
		def banRemoteRequests (web_view, frame, web_resource, request, response):
			if not request.get_uri().startswith('file://'):
				request.set_uri('about:blank')
				
		if manifest.origin == 'local': browser.connect('resource-request-starting', banRemoteRequests)
		
		def banOtherMime (web_view, frame, request, mimetype, policy_decision):
			if mimetype != 'text/html':
				policy_decision.ignore()
				return True
			
		browser.connect('mime-type-policy-decision-requested', banOtherMime)
		
		

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
	def event_to_json(self, w, *args):
		dict = {}
		#on gtk event
		if(isinstance(args[0], gtk.gdk.Event)):
			dict = self.attrs_to_dict(args[0])
			dict['type'] = args[0].type.value_name
		elif(isinstance(args[0], gtk.gdk.DragContext)): #on drag context
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
	
	def load_widget(self, browser, origin, source):
		if origin != 'hosted':
			file = os.path.abspath(source)
			source = 'file://' + urllib.pathname2url(file)
		browser.load_uri(source)
	
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
		window,browser = self.prepare_widget(manifest, module)
		
		self.load_widget(browser, manifest.origin, path+manifest.source)
	
		return manifest, module, window, browser
		
	def __init__(self, path, custom_manifest = None):
		self.manifest,self.module,self.window,self.browser = self.init_widget(path, custom_manifest)
