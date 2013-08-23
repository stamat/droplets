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
	
	
	path = sys.argv[1]



	mainDrop = Droplet(path, mfest)
		
		
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

