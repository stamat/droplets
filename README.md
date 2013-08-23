![Droplets - Linux html/css/javascript GUI frontend framework for widgets and apps written in Python for GTK+ with webkit webview](droplets_logo.png)
========

Linux html/css/javascript GUI frontend framework for widgets and apps written in Python for GTK+ with webkit webview

Notes
-----
* Origins can be local, remote and hosted. Hosted is a remote origin with a base not loaded localy. With hosted everything except manifest is remote. See how hosted applications can have local setting files

* Manifest should have uri of the starting page

TO DOs:
-------
[ ] Separate settings from manifest - example: x and y are settings, width, height and resize are manifest 

[ ] Move the droplet menu to droplet.py from droplets.py

[ ] Complete the menu and enable it with basic functionality like move toggle, stick toggle, 

[ ] If stick is off, remember the widget screen in settings, gtk.Window.set_screen, gtk.Window.get_screen - http://www.pygtk.org/docs/pygtk/class-gtkwindow.html

[ ] Each droplet should be a gtk program for itself, so move a gtk thread in droplet.py too

[ ] Define a settings file

[ ] Build droplet process manager, and settings manager

[ ] Disable webkit to resize gtk.Window

Dependencies
------------
python-webkit

python-gtk2

python-cairo
