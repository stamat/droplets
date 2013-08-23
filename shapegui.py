#!/usr/bin/env python
# A simple demonstration of using cairo to shape windows.
# Natan 'whatah' Zohar
import gtk
import math

class ShapedGUI:
    def __init__(self):
        self.window = gtk.Window()
        self.window.show() # We show here so the window gets a border on it by the WM
        x,y,w,h = self.window.get_allocation()
        self.window.set_size_request(w,h)
#        self.window.connect('size-allocate', self.reshaperect)
        self.window.connect('size-allocate', self.reshapecircle)
        self.window.set_decorated(False)
        self.window.show()

    # Shape the window into a rounded rectangle
    def reshaperect(self, obj, allocation):
        w,h = allocation.width, allocation.height
        bitmap = gtk.gdk.Pixmap(None, w, h, 1)
        
        # Clear the bitmap
        fg = gtk.gdk.Color(pixel=0)
        bg = gtk.gdk.Color(pixel=-1)
        fg_gc = bitmap.new_gc(foreground=fg, background=bg)
        bitmap.draw_rectangle(fg_gc, True, 0, 0, w, h)

        # Draw our shape into the pixmap using cairo
        # Let's try drawing a rectangle with rounded edges.
        padding=5 # Padding from the edges of the window
        rounded=30 # How round to make the edges
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
        self.window.shape_combine_mask(bitmap, 0, 0)
        self.window.show()


    # Reshape the window into a circle
    def reshapecircle(self, obj, allocation):
        w,h = allocation.width, allocation.height
        bitmap = gtk.gdk.Pixmap(None, w, h, 1)
        
        # Clear the bitmap 
        fg = gtk.gdk.Color(pixel=0)
        bg = gtk.gdk.Color(pixel=-1)
        fg_gc = bitmap.new_gc(foreground=fg, background=bg)
        bitmap.draw_rectangle(fg_gc, True, 0, 0, w, h)

        # Draw our shape into the bitmap using cairo      
        cr = bitmap.cairo_create()
        cr.set_source_rgb(0,0,0)
        cr.arc(w/2,h/2,min(h,w)/2,0,2*math.pi)
        cr.fill()

        # Set the window shape
        self.window.shape_combine_mask(bitmap, 0, 0)
        self.window.show()

shapedWin = ShapedGUI()
gtk.main()
