![Droplets - Linux html/css/javascript GUI frontend framework for widgets and apps written in Python for GTK+ with webkit webview](droplets_logo.png)
========

Linux HTML/CSS/JavaScript GUI frontend framework for widgets and apps written in Python for GTK+ with webkit webview

Enables you to unleash your creativity while developing GUI frontends for Linux desktop applications or have fancy customizable easy to develop widgets on your desktop. An online store will be included in near future.

It's like Google Chrome packaged apps plus widget engine, but without a lot of constraints, and without Google Chrome. 

![SCREENSHOT](https://i.imgur.com/RUpVIui.jpg)

Security model is very simple: 
* Local apps don’t use the webview to make remote calls (loaded webpage is used only as a GUI interface), they can do everything on the system (even do CURL requests) by the privileges the apps were run on through the Python interface script which functions the JavaScript of the app can call.
* Remote apps don’t have any access to the system, but they are stored locally and can function as any web app making calls to cross domain allowed services, load remote resources or make JSONP requests.
* Hosted apps are hosted remotely, they are exactly like web apps opened in browser.

Or if you haven’t heard about Chrome apps, it is like PhoneGap for the Linux desktop combined with Dashboard Widgets, or Windows Gadgets but more secure.


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
[ ] Window shape mask from the image gtk.gdk.pixbuf_new_from_file(filename) ? then convert Pixbuf to Pixmap. The Pixmap inherits gtk.gdk.Drawable thus something like this might work gtk.gdk.Drawable.draw_pixbuf, and pixpuf has gtk.gdk.pixbuf_new_from_file

[ ] Make an JavaScript API maybe...? Embed javascript from file with send and recieve functionality...

[ ] A way to name the python process? Risk the portability for that? http://code.google.com/p/procname/ Is it worth it?

[ ] Whenever a droplet is started it invokes the interwidget communicaton system.

[ ] Set StatusIcon for the app and widget manager

[ ] Implement json validator to validate manifest, and settings.

[ ] Separate settings from manifest - example: x and y are settings, width, height and resize are manifest 

[ ] Complete the menu and enable it with basic functionality like move toggle, stick toggle, above toggle, disable, settings invoke, reload

[ ] If stick is off, remember the widget screen in settings, gtk.Window.set_screen, gtk.Window.get_screen

[ ] If app is resizable store the values in settings

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
