#!/usr/bin/env python

##
# Project: DROPLETS
# ~ Linux and Windows Web GUI and Widget framework.~
# www.droplets.info
# December 2012. Armageddon :P
#
# @author Nikola Stamatovic Stamat <stamat@ivartech.com>
##

#==== BUGS ====#
#TODO: Browser resize on URL change! Forbid resize!
#TODO: Multi window opacity in the same gtk thread, last one is fully transparent

import sys, gtk, threading
import re
from droplets.droplet import Droplet
			
def main(args):
#	global path
#	if path[len(path)-1] != '/':
#		path = path + '/'
	
	mfest = None
	try:	
		mfest = sys.argv[2]
	except IndexError:
		pass
	
	
	#global path
	path = sys.argv[1]
	#global manifest, module, window, browser
	#manifest, module, window, browser = init_widget(path)
	
	#TODO: instance another widget to move the present one	
	
	flag = True
	
	def show_handle():
		print 'lol'
		handle.window.show_all()
		x,y = mainDrop.window.get_position()
		#print x, y, handle.manifest.height
		handle.droplet_move(x, y-handle.manifest.height+1)
		
	def hide_handle():
		print 'omg'
		print flag
		if flag:
			handle.window.hide_all()
			
	def enter_handle():
		print 'zomg'
		flag = False
		
	def leave_handle():
		print 'zlol'
		flag = True
		hide_handle()
		
	def set_timeout(func, sec):		
		t = None
		def func_wrapper():
			func()	
			t.cancel()
		t = threading.Timer(sec, func_wrapper)
		t.start()
		
	def set_interval(func, sec):
		def func_wrapper():
			set_interval(func, sec)	
			func()	
		t = threading.Timer(sec, func_wrapper)
		t.start()
		return t
		
	mainDrop = Droplet(path, mfest)
	if mainDrop.manifest.handle_enabled:
		def show_handle_wrapper(w, e): show_handle()
		mainDrop.window.connect('enter-notify-event', show_handle_wrapper)

		def hide_handle_wrapper(w, e): set_timeout(hide_handle, 0.5)
		mainDrop.window.connect('leave-notify-event', hide_handle_wrapper)
	
		handle = Droplet('system/handle')
		def enter_handle_wrapper(w, e): enter_handle()
		handle.window.connect('enter-notify-event', enter_handle_wrapper)
		def leave_handle_wrapper(w, e): leave_handle()
		handle.window.connect('leave-notify-event', leave_handle_wrapper)
		
		def handle_press_wrapper(w, e): 
			if e.button == 1:
				handle.droplet_drag(e.button, int(e.x_root), int(e.y_root), e.time)
				def follow(w, e):
					mainDrop.window.move(e.x, e.y+handle.manifest.height-1)
				handle.window.connect('configure-event', follow)
				
		handle.browser.connect('button-press-event', handle_press_wrapper)
		# handle.window.disconnect('configure-event')
		
		
	def toggleMove(*args):
		label = args[0].get_label()
		parsed = re.match('(?P<pref>.*:\s*)(?P<state>.*)$', label)
		state = parsed.group('state')
		pref = parsed.group('pref')
		
		if state == 'Off':
			mainDrop.droplet_drag_disable()
			args[0].set_label(pref+'On')
		elif state == 'On':
			mainDrop.droplet_drag_enable()
			args[0].set_label(pref+'Off')
	
	def detachFn(*args):
		print args
	
	#TODO: ONLY ON WIDGETS!!! toggle bool in manifest
	menu = gtk.Menu()
	remove_menu = gtk.Menu()
	menu.attach_to_widget(mainDrop.browser, detachFn) ##TODO: see what a fuckin' detach function is
	
	movetoggle = gtk.MenuItem("Move: Off")
	properties = gtk.MenuItem("Properties")
	
	remove_submenu = gtk.MenuItem("Deactivate")
	remove_submenu.set_submenu(remove_menu)
	remove = gtk.MenuItem("X")
	remove_menu.append(remove);
	
	menu.append(movetoggle)
	menu.append(properties)
	menu.append(remove_submenu)
	movetoggle.show()
	properties.show()
	remove.show()
	remove_submenu.show()
	
	if not mainDrop.manifest.drag:
			movetoggle.set_label("Move: On")
	
	movetoggle.connect('button-press-event', toggleMove)
	remove.connect('button-press-event', mainDrop.droplet_deactivate)
	
	
	def _on_button_press_event(self, event, widget):
		if event.button == 3:
			widget.popup(None, None, None, 0, event.time)
			pass
	
	mainDrop.browser.connect('button_press_event',_on_button_press_event, menu)
	
	#main3 = Droplet(path)
	#main4 = Droplet(path)
	#print dir(mainDrop.window.get_display())
	
	#gtk.gdk.Window.shape_combine_mask
	
	gtk.main()

	return True

if __name__ == '__main__':
    sys.exit(main(sys.argv))    

