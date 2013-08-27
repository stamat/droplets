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

import sys, gtk
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
	
	

if __name__ == '__main__':
    sys.exit(main(sys.argv))    

