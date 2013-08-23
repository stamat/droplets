![Droplets - Linux html/css/javascript GUI frontend framework for widgets and apps written in Python for GTK+ with webkit webview](droplets_logo.png)
========

Linux html/css/javascript GUI frontend framework for widgets and apps written in Python for GTK+ with webkit webview

Why?
----
Have you ever wanted bits of the mighty Internet on your desktop? Just to stay informed at a glance. 

write this

Face it, every developer that tried Java, got frustrated by SWING... Fuck. Even mentioning it gives me shivers. I dont like Glade either. Nokia had some cool builder with Qt, but it gets hadned from hand to hand, the poor Qt...
I am used to building web interfaces, because they are so easy to design

Notes
-----
* Origins can be local, remote and hosted. Hosted is a remote origin with a base not loaded localy. With hosted everything except manifest is remote. See how hosted applications can have local setting files

* Widgets can be either completely local or completely remote in a sense of resources. A web widget cannot have a communication with the system, a local widget cannot have a communication to the web through HTTP, only through python interface, thus disabling a chance that it can accidentaly load malicius scripts that can be changed by the third party

* Type can be app or widget. Apps should always have window decoration, widgets should not have decoration, and always have right click menu enabled

* Manifest - everything that makes the app/widget manifest itself on the screen, these values wont be changed by the users interaction
	"title": [null, 0],
	"description": [null, 0],
	"uid": [null, 0], // special identificator, generated after the first run and used for interwidget communication
	"type": ["widget", 0],
	"height": [300, 1],  // default size
	"width": [300, 1], // default size
	"icon": [null, 0],
	"executable": ["main", 0],
	"origin": ["local", 0],
	"source": ["index.html", 0],
	"skip_pager": [false, 0],
	"decorated": [false, 0], 
	"skip_taskbar": [false, 0], 
	"default_context_menu": [false, 0],
	"shape": ["rect", 0],
	"corner_radius": [0, 0],
	"resizable": [false, 0],

* Properties and settings - window behaviour flags andapplication/widget specific variables that an be changed.

TO DOs:
-------

[ ] Implement json validator to validate manifest, settings and properties.

[ ] Separate settings from manifest - example: x and y are settings, width, height and resize are manifest 

[ ] Move the droplet menu to droplet.py from droplets.py

[ ] Complete the menu and enable it with basic functionality like move toggle, stick toggle, above toggle, disable, settings invoke, reload

[ ] If stick is off, remember the widget screen in settings, gtk.Window.set_screen, gtk.Window.get_screen

[ ] If app is resizable store the values in settings

[ ] Each droplet should be a gtk thread for itself, so move a gtk thread in droplet.py too

[ ] Define a settings file

[ ] Build droplet process manager, and settings manager

[ ] Disable webkit to resize gtk.Window

[ ] Comment the goddamn code!!! >:/

[ ] Include some kick ass bootstrap and the ability to theme it

[ ] build a web store service!!! Register, upload, comment and rate, install. Install from inside a droplets manager. Allow remote calls only towards the webstore and only for the manager.

[ ] A way of local widgets to invoke one another and communicate. Maybe some simple communication server like d-bus. Or something like one app can have multiple widgets or windows packed... this is a real advancement, maybe for 2.0 in some not so near future

----

Fun projects to test and perfect the framework(sorted by complexity):

[ ] Build a digital clock, calendar and a weather demo widgets

[ ] Build a simple notepad, music player, browser demo apps

[ ] Build a simple, and later more complex XMPP chat client using strophe.js

[ ] Build dock and application menu, and notification area

[ ] Try to build a live desktop, just for fun.

[ ] Build a desktop environment salvaging Xfce called Puddle that utilizes widgets and apps noted above

[ ] Build a debian distro... i always wanted that, ambicious arent i?


Dependencies
------------
python-webkit 

python-gtk2 >= 2.9

python-cairo

Literature
----------
http://webkitgtk.org/reference/webkitgtk/stable/webkitgtk-webkitwebview.html

http://www.pygtk.org/docs/pygtk/class-gtkwindow.html


Author
------
Nikola Stamatovic Stamat
ivartech

Licence
-------
Havent decided yet...
