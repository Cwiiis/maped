from tkinter import *
from tkinter import filedialog
from tkinter import font
from tkinter import messagebox
from tkinter import simpledialog
from tkinter import ttk
from types import SimpleNamespace
from zipfile import ZipFile
import base64
import collections
import json
import math
import pathlib
import png
import platform
import re
import struct
import zipfile

TAG_PALETTE = ['#edd400', '#f57900', '#c17d11', '#73d216',
               '#3465a4', '#75507b', '#cc0000', '#555753',
               '#555753']

class Ctx:
    class __serialiser__:
        def __init__(self, ctx):
            self.tiles = []
            for tile in ctx.tiles:
                self.tiles.append(base64.b64encode(tile).decode())
            self.data = []
            for datum in ctx.data_tree.get_children():
                self.data.append(ctx.data_tree.item(datum)['values'])
            for attr in ['map', 'tags', 'notes', 'entity_size', 'entities',
                         'palette', 'width', 'height', 'mode',
                        'tile_width', 'tile_height']:
                setattr(self, attr, getattr(ctx, attr))

        def __repl_func__(self, match: re.Match):
            return " ".join(match.group().split())
        
        def toJSON(self):
            return re.sub(r"(?<=\[)[^\[\]]+(?=])", self.__repl_func__,
                json.dumps(self, default=lambda o: o.__dict__, indent=4))

    def __init__(self):
        self.canvas = None # Main map drawing canvas
        self.clipboard = None # The last thing copied or cut [ width, height, [tilemap] ]
        self.tiles_canvas = None # Tiles drawing canvas
        self.main_frame = None # Main window frame
        self.property_widgets = [] # List of widgets that require a selection
        self.note_text = None # The Text widget for cell notes
        self.set_cell_tag = None # Callback (tag, desc) to update the cell properties UI
        self.data_tree = None # Treeview containing cell data (id, data, desc)
        self.entity_tree = None # Treeview containing entity list (x, y, desc)
        self.entity_data_tree = None # Treeview to show individual entity data (data)
        self.status_left = None # Status bar text variable
        self.status_right = None # Status bar text variable
        self.menu = None # Main menubar
        self.zoom = 1 # Current map zoom level (must be whole number)
        self.draw_grid = False
        self.draw_tags = True
        self.draw_entities = True

    def reset(self):
        self.name = None # Open file name
        self.tiles = [] # Tile store (in binary CPC pixel format)
        self.map = [] # Tile map
        self.tags = [] # Tile tags map
        self.notes = [] # Map of notes for cells in tile map
        self.entity_size = 4
        self.entities = [] # Entity list (x, y, desc, [[data, desc]+])
        self.palette = [] # Palette as hex values
        self.width = 0 # Map width in tiles
        self.height = 0 # Map height in tiles
        self.mode = 0 # CPC screen mode
        self.tile_width = 8
        self.tile_height = 8
        self.selection = None # List of top-left and bottom-right tile coordinate lists
        self.data_tree.delete(*self.data_tree.get_children())
        self.entity_tree.delete(*self.entity_tree.get_children())
        self.entity_data_tree.delete(*self.entity_data_tree.get_children())
        self.note_text.delete('1.0', END)
        update_selection()

    def load(self, data):
        obj = json.loads(data, object_hook=lambda d: SimpleNamespace(**d))
        self.tiles = []
        for tile in obj.tiles:
            self.tiles.append(base64.b64decode(tile))
        self.data_tree.delete(*self.data_tree.get_children())
        for datum in obj.data:
            self.data_tree.insert('', END, values=datum)
        for attr in ['map', 'tags', 'notes', 'entity_size', 'entities',
                     'palette', 'width', 'height', 'mode',
                    'tile_width', 'tile_height']:
            setattr(self, attr, getattr(obj, attr))
        
        self.entity_tree.delete(*self.entity_tree.get_children())
        self.entity_data_tree.delete(*self.entity_data_tree.get_children())
        for entity in self.entities:
            self.entity_tree.insert('', END, values=(entity[0], entity[1], entity[2]))

    def toJSON(self):
        return Ctx.__serialiser__(self).toJSON()

ctx = Ctx()


def get_pixel(tile, x, y):
    pixel = 0
    pixels_per_byte = 2 if ctx.mode == 0 else (4 if ctx.mode == 1 else 8)
    cpc_pixel = tile[(int(ctx.tile_width / pixels_per_byte) * y) + int(x // pixels_per_byte)]
    # TODO: Verify mode 2 and 1 are correct here
    if ctx.mode == 2:
        pixel = (cpc_pixel & (1 << (x % 8))) >> (x % 8)
    elif ctx.mode == 1:
        cpc_pixel = cpc_pixel << (x % 4)
        pixel = ((cpc_pixel & 0b10000000) >> 7) | ((cpc_pixel & 0b00001000) >> 2)
    elif ctx.mode == 0:
        cpc_pixel = cpc_pixel << (x % 2)
        pixel = ((cpc_pixel & 0b10000000) >> 7) | \
                ((cpc_pixel & 0b00001000) >> 2) | \
                ((cpc_pixel & 0b00100000) >> 3) | \
                ((cpc_pixel & 0b00000010) << 2)

    return pixel

def get_byte(row, offset, mode):
    cpc_pixel = 0
    if mode == 2:
        cpc_pixel = (row[offset] << 7) | \
                    (row[offset+1] << 6) | \
                    (row[offset+2] << 5) | \
                    (row[offset+3] << 4) | \
                    (row[offset+4] << 3) | \
                    (row[offset+5] << 2) | \
                    (row[offset+6] << 1) | \
                    row[offset+7]
    elif mode == 1:
        pixel0 = row[offset]
        pixel1 = row[offset+1]
        pixel2 = row[offset+2]
        pixel3 = row[offset+3]
        cpc_pixel = ((pixel0 & 0b01) << 7) | ((pixel1 & 0b01) << 6) | \
                    ((pixel2 & 0b01) << 5) | ((pixel3 & 0b01) << 4) | \
                    ((pixel0 & 0b10) << 2) | ((pixel1 & 0b10) << 1) | \
                    ((pixel2 & 0b10)) | ((pixel3 & 0b10) >> 1)
    elif mode == 0:
        pixel0 = row[offset]
        pixel1 = row[offset+1]
        cpc_pixel = (0b10000000 if (pixel0 & 0b0001) != 0 else 0) | \
                    (0b01000000 if (pixel1 & 0b0001) != 0 else 0) | \
                    (0b00100000 if (pixel0 & 0b0100) != 0 else 0) | \
                    (0b00010000 if (pixel1 & 0b0100) != 0 else 0) | \
                    (0b00001000 if (pixel0 & 0b0010) != 0 else 0) | \
                    (0b00000100 if (pixel1 & 0b0010) != 0 else 0) | \
                    (0b00000010 if (pixel0 & 0b1000) != 0 else 0) | \
                    (0b00000001 if (pixel1 & 0b1000) != 0 else 0)
    return cpc_pixel

def validate_number(S):
    return S.isdecimal()

def update_status():
    ctx.status_left.set('%d x %d, %d %dx%d tiles, mode %d' % \
        (ctx.width, ctx.height, len(ctx.tiles),
         ctx.tile_width, ctx.tile_height, ctx.mode))

# TODO: Adjust scroll to zoom around the current cursor position/selection?
def adjust_zoom(delta, force=False):
    if len(ctx.tiles) == 0:
        return
    
    new_zoom = int(max(1, min(4, ctx.zoom + delta)))
    if new_zoom == ctx.zoom and not force:
        return
    old_zoom = ctx.zoom
    ctx.zoom = new_zoom
    
    # Store the old xview/yview to work out the new centre
    xview = ctx.canvas.xview()
    yview = ctx.canvas.yview()

    width_scale = 2 if ctx.mode == 0 else 1
    height_scale = 2 if ctx.mode == 2 else 1
    img = ctx.canvas.image.zoom(width_scale * ctx.zoom, height_scale * ctx.zoom)
    ctx.canvas.config(scrollregion=(0, 0, img.width(), img.height()))
    ctx.canvas.delete('image')
    ctx.canvas.create_image((img.width()/2, img.height()/2), image=img, tags='image')
    ctx.canvas.zoomed_image = img

    # Reset the scroll position after zoom change
    view_scale = old_zoom / new_zoom
    newxview = max(0, xview[0] + ((xview[1] - xview[0]) / 2 * (1.0 - view_scale)))
    newyview = max(0, yview[0] + ((yview[1] - yview[0]) / 2 * (1.0 - view_scale)))
    ctx.canvas.xview_moveto(newxview)
    ctx.canvas.yview_moveto(newyview)

    redraw_grid()
    redraw_entities()
    update_selection()

def tile_coords_from_coords(e):
    x = ctx.canvas.canvasx(e.x)
    y = ctx.canvas.canvasy(e.y)
    width_scale = (2 if ctx.mode == 0 else 1) * ctx.zoom
    height_scale = (2 if ctx.mode == 2 else 1) * ctx.zoom
    if x < 0 or x >= ctx.width * ctx.tile_width * width_scale:
        return None
    if y < 0 or y >= ctx.height * ctx.tile_height * height_scale:
        return None
    
    tilex = int((x / width_scale) // ctx.tile_width)
    tiley = int((y / height_scale) // ctx.tile_height)
    return [tilex, tiley]

def entry_has_focus(root):
    focus = root.focus_get()
    return isinstance(focus, Entry) or isinstance(focus, ttk.Entry) or isinstance(focus, Text)

def copy(root, cut=False):
    if ctx.selection is None or entry_has_focus(root):
        return

    x1 = min(ctx.selection[0][0], ctx.selection[1][0])
    x2 = max(ctx.selection[0][0], ctx.selection[1][0]) + 1
    y1 = min(ctx.selection[0][1], ctx.selection[1][1])
    y2 = max(ctx.selection[0][1], ctx.selection[1][1]) + 1

    ctx.clipboard = [x2 - x1, y2 - y1, [], []]
    for x in range(x1, x2):
        for y in range(y1, y2):
            i = x * ctx.height + y
            ctx.clipboard[2].append(ctx.map[i])
            ctx.clipboard[3].append(ctx.tags[i])
            if cut:
                ctx.map[i] = 0
                ctx.tags[i] = 0
    if cut:
        redraw_map()

def paste(root, ):
    if ctx.selection is None or ctx.selection[0] != ctx.selection[1] or entry_has_focus(root):
        return
    for x in range(0, ctx.clipboard[0]):
        for y in range(0, ctx.clipboard[1]):
            if x + ctx.selection[0][0] >= ctx.width or y + ctx.selection[0][1] >= ctx.height:
                continue
            i = x * ctx.clipboard[1] + y
            mi = (ctx.selection[0][0] + x) * ctx.height + (ctx.selection[0][1] + y)
            ctx.map[mi] = ctx.clipboard[2][i]
            ctx.tags[mi] = ctx.clipboard[3][i]
    redraw_map()

def update_selection():
    editmenu = ctx.menu.nametowidget(ctx.menu.entrycget('Edit', 'menu'))

    if ctx.selection is None:
        for widget in ctx.property_widgets:
            widget.config(state=DISABLED)
        ctx.note_text.config(state=DISABLED)
        ctx.canvas.delete('selection')
        editmenu.entryconfig('Cut', state='disabled')
        editmenu.entryconfig('Copy', state='disabled')
        editmenu.entryconfig('Paste', state='disabled')
        return

    editmenu.entryconfig('Cut', state='normal')
    editmenu.entryconfig('Copy', state='normal')

    if ctx.selection[0] == ctx.selection[1]:
        if ctx.clipboard is not None:
            editmenu.entryconfig('Paste', state='normal')
        ctx.note_text.config(state=NORMAL)
    else:
        editmenu.entryconfig('Paste', state='disabled')
        ctx.note_text.config(state=DISABLED)
    for widget in ctx.property_widgets:
        widget.config(state=NORMAL)

    # Work out selection coordinates
    x1 = min(ctx.selection[0][0], ctx.selection[1][0])
    x2 = max(ctx.selection[0][0], ctx.selection[1][0]) + 1
    y1 = min(ctx.selection[0][1], ctx.selection[1][1])
    y2 = max(ctx.selection[0][1], ctx.selection[1][1]) + 1
    i = x1 * ctx.height + y1

    width_scale = (2 if ctx.mode == 0 else 1) * ctx.zoom
    height_scale = (2 if ctx.mode == 2 else 1) * ctx.zoom
    x1 *= ctx.tile_width * width_scale
    x2 *= ctx.tile_width * width_scale
    y1 *= ctx.tile_height * height_scale
    y2 *= ctx.tile_height * height_scale

    rect = ctx.canvas.find_withtag('selection')
    if len(rect) == 0:
        ctx.canvas.create_rectangle((x1, y1, x2, y2), tags=['selection'], width=max(2, ctx.zoom))
    else:
        ctx.canvas.itemconfig(rect[0], width=max(2, ctx.zoom))
        ctx.canvas.coords(rect[0], x1, y1, x2, y2)
        ctx.canvas.lift(rect[0])

    # Update cell tag
    if ctx.selection[0] == ctx.selection[1]:
        ctx.set_cell_tag(ctx.tags[i], ctx.notes[i])

def map_coords_from_event(e):
    x = ctx.canvas.canvasx(e.x)
    y = ctx.canvas.canvasy(e.y)
    width_scale = (2 if ctx.mode == 0 else 1) * ctx.zoom
    height_scale = (2 if ctx.mode == 2 else 1) * ctx.zoom
    return (int(x / width_scale), int(y / height_scale))

def entity_at_point(x, y):
    for i in range(len(ctx.entities)):
        if x > ctx.entities[i][0] - 4 and x < ctx.entities[i][0] + 4 and \
           y > ctx.entities[i][1] - 4 and y < ctx.entities[i][1] + 4:
            return i
    return -1

def canvas_motion(e):
    if e.state & 0x0100: # Button1 mask (FIXME: this must be defined somewhere?)
        i = tile_coords_from_coords(e)
        if i is not None:
            ctx.selection[1] = i
            update_selection()
    
    (x, y) = map_coords_from_event(e)
    i = entity_at_point(x, y)
    if i == -1:
        ctx.status_right.set('(%d, %d)' % (x, y))
    else:
        ctx.status_right.set('%s (%d, %d)' % (ctx.entities[i][2], x, y))

def canvas_release(e):
    i = tile_coords_from_coords(e)
    if i is not None:
        ctx.selection[1] = i
        update_selection()

    if ctx.selection is not None:
        # Make sure selection is always top-left, bottom-right
        # FIXME: We need to stop code using selections until they're completed here
        x1 = min(ctx.selection[0][0], ctx.selection[1][0])
        x2 = max(ctx.selection[0][0], ctx.selection[1][0])
        y1 = min(ctx.selection[0][1], ctx.selection[1][1])
        y2 = max(ctx.selection[0][1], ctx.selection[1][1])
        ctx.selection[0][0] = x1
        ctx.selection[1][0] = x2
        ctx.selection[0][1] = y1
        ctx.selection[1][1] = y2

def canvas_press(e):
    ctx.canvas.focus_set()

    # If we've clicked an entity, select it (should we disable selection when this happens?)
    (x, y) = map_coords_from_event(e)
    i = entity_at_point(x, y)
    if i != -1:
        ctx.entity_tree.selection_set(ctx.entity_tree.get_children()[i])

    if ctx.map is None:
        return
    
    i = tile_coords_from_coords(e)
    if i is None:
        ctx.selection = None
        update_selection()
        return

    ctx.selection = [i, i]
    update_selection()

def canvas_alt_press(e, root):
    (x, y) = map_coords_from_event(e)
    i = entity_at_point(x, y)
    if i == -1:
        add_entity(root, [x, y, ''])
    else:
        ctx.entity_tree.selection_set(ctx.entity_tree.get_children()[i])
        edit_entity(root)

def canvas_mousewheel(e):
    delta = 0.0
    if platform.system() == 'Windows':
        delta = e.delta/120
    elif platform.system() == 'Darwin':
        delta = e.delta
    else:
        if e.num == 4:
            e.delta = 1
        elif e.num == 5:
            e.delta = -1
    adjust_zoom(delta)

def canvas_entered(e):
    canvas = e.widget
    if platform.system() == 'Linux':
        canvas.bind_all("<Button-4>", canvas_mousewheel)
        canvas.bind_all("<Button-5>", canvas_mousewheel)
    else:
        canvas.bind_all("<MouseWheel>", canvas_mousewheel)

def canvas_left(e):
    canvas = e.widget
    if platform.system() == 'Linux':
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")
    else:
        canvas.unbind_all("<MouseWheel>")

def canvas_scroll(root, x, y):
    if entry_has_focus(root):
        return
    
    xview = ctx.canvas.xview()
    yview = ctx.canvas.yview()

    if x < 0 and xview[0] > 0.0:
        ctx.canvas.xview_moveto(max(0, xview[0] - 1.0/ctx.width))
    elif x > 0 and xview[1] < 1.0:
        ctx.canvas.xview_moveto(min(1.0 - (xview[1] - xview[0]), xview[0] + 1.0/ctx.width))

    if y < 0 and yview[0] > 0.0:
        ctx.canvas.yview_moveto(max(0, yview[0] - 1.0/ctx.height))
    elif y > 0 and yview[1] < 1.0:
        ctx.canvas.yview_moveto(min(1.0 - (yview[1] - yview[0]), yview[0] + 1.0/ctx.height))

def tiles_canvas_clicked(e):
    if ctx.selection is None:
        return
    
    target = ctx.tiles_canvas.find_overlapping(ctx.tiles_canvas.canvasx(e.x),
                                               ctx.tiles_canvas.canvasy(e.y),
                                               ctx.tiles_canvas.canvasx(e.x),
                                               ctx.tiles_canvas.canvasy(e.y))
    if len(target) != 1:
        return
    
    tile = int(ctx.tiles_canvas.gettags(target[0])[0])
    for y in range(ctx.selection[0][1], ctx.selection[1][1]+1):
        for x in range(ctx.selection[0][0], ctx.selection[1][0]+1):
            ctx.map[x * ctx.height + y] = tile
            draw_map_tile(x, y)
    adjust_zoom(0, True)

def tiles_canvas_alt_clicked(e):
    target = ctx.tiles_canvas.find_overlapping(ctx.tiles_canvas.canvasx(e.x),
                                               ctx.tiles_canvas.canvasy(e.y),
                                               ctx.tiles_canvas.canvasx(e.x),
                                               ctx.tiles_canvas.canvasy(e.y))
    if len(target) != 1:
        return
    
    idx = int(ctx.tiles_canvas.gettags(target[0])[0])
    if idx == 0:
        return
    
    old_tile = ctx.tiles[0]
    ctx.tiles[0] = ctx.tiles[idx]
    ctx.tiles[idx] = old_tile
    
    for i in range(0, ctx.width * ctx.height):
        if ctx.map[i] == 0:
            ctx.map[i] = idx
        elif ctx.map[i] == idx:
            ctx.map[i] = 0

    redraw_tiles()

def store_cell_tag(number):
    if ctx.selection is not None:
        changed = False
        for y in range(ctx.selection[0][1], ctx.selection[1][1] + 1):
            for x in range(ctx.selection[0][0], ctx.selection[1][0] + 1):
                i = x * ctx.height + y
                if ctx.tags[i] != number:
                    changed = True
                    ctx.tags[i] = number
                    if ctx.draw_tags:
                        draw_map_tile(x, y)
        if changed and ctx.draw_tags:
            adjust_zoom(0, True)

def update_hex(number, hex_text):
    hex_text[0].set('%x' % (number >> 4))
    hex_text[1].set('%x' % (number & 0xF))

def number_widgets_update(text, buttons, hex_text):
    number = int(text.get())
    for bit in range(0, 8):
        if number & (1 << bit) != 0:
            buttons[bit].text.set('1')
            buttons[bit].configure(relief=SUNKEN, bg='black', fg='white')
        else:
            buttons[bit].text.set('0')
            buttons[bit].configure(relief=RAISED, bg='white', fg='black')
    update_hex(number, hex_text)
    store_cell_tag(number)

def toggle_bit(buttons, bit, text, hex_text):
    number = int(text.get())
    if number & (1 << bit) != 0:
        number &= ~(1 << bit)
    else:
        number |= (1 << bit)
    text.set(str(number))
    number_widgets_update(text, buttons, hex_text)

def note_modified():
    ctx.note_text.edit_modified(False)
    if ctx.selection is None:
        return
    for y in range(ctx.selection[0][1], ctx.selection[1][1]+1):
        for x in range(ctx.selection[0][0], ctx.selection[1][0]+1):
            ctx.notes[x * ctx.height + y] = ctx.note_text.get('1.0', END).rstrip()

def update_cell_tag(number, desc, tag_entry):
    ctx.note_text.unbind('<<Modified>>')
    tag_entry.set(number)
    ctx.note_text.delete('1.0', END)
    ctx.note_text.insert('1.0', desc)
    ctx.note_text.edit_reset()
    ctx.note_text.bind('<<Modified>>', lambda e: note_modified())

def apply_cell_tag_to_similar():
    if ctx.selection is None:
        return
    changed = False
    for y in range(0, ctx.height):
        for x in range(0, ctx.width):
            # Don't check inside the selection
            if x >= min(ctx.selection[0][0], ctx.selection[1][0]) and \
               x <= max(ctx.selection[0][0], ctx.selection[1][0]) and \
               y >= min(ctx.selection[0][1], ctx.selection[1][1]) and \
               y <= max(ctx.selection[0][1], ctx.selection[1][1]):
                continue

            # Check if this bit of the map matches the selection
            same = True
            for sy in range(ctx.selection[0][1], ctx.selection[1][1]+1):
                for sx in range(ctx.selection[0][0], ctx.selection[1][0]+1):
                    mx = x + (sx - ctx.selection[0][0])
                    my = y + (sy - ctx.selection[0][1])
                    i = mx * ctx.height + my
                    si = sx * ctx.height + sy
                    if ctx.map[i] != ctx.map[si]:
                        same = False
                        break
                if not same:
                    break
            if not same:
                continue

            # Update the tags and redraw that part of the map
            for sy in range(ctx.selection[0][1], ctx.selection[1][1]+1):
                for sx in range(ctx.selection[0][0], ctx.selection[1][0]+1):
                    mx = x + (sx - ctx.selection[0][0])
                    my = y + (sy - ctx.selection[0][1])
                    i = mx * ctx.height + my
                    si = sx * ctx.height + sy
                    ctx.tags[i] = ctx.tags[si]
                    draw_map_tile(mx, my)
                    changed = True
    if changed:
        adjust_zoom(0, True)

def edit_entity_data(root):
    selection = ctx.entity_tree.selection()
    if len(selection) < 1:
        return
    i = ctx.entity_tree.index(selection[0])

    for item in ctx.entity_data_tree.selection():
        j = ctx.entity_data_tree.index(item)
        d = EntityDataDialog(root, ctx.entities[i][3][j]).result
        if d is None:
            continue
        ctx.entities[i][3][j][0] = d['data']
        ctx.entities[i][3][j][1] = d['desc']
        ctx.entity_data_tree.item(item, values=ctx.entities[i][3][j])

class EntityDataDialog(simpledialog.Dialog):
    def __init__(self, parent, data):
        self.defaults = data
        super().__init__(parent, 'Edit entity data')

    def body(self, master):
        master.pack(expand=True, fill=BOTH, padx=5, pady=5)

        ttk.Label(master, text='Data').grid(row=0, column=0, sticky=W, padx=5, pady=5)
        ttk.Label(master, text='Description').grid(row=1, column=0, sticky=W, padx=5, pady=5)

        self.data_entry = Spinbox(master, from_=0, to=255)
        self.desc_entry = ttk.Entry(master)

        self.data_entry.grid(row=0, column=1, sticky=EW)
        self.desc_entry.grid(row=1, column=1, sticky=EW)

        if self.defaults is not None:
            self.data_entry.delete(0)
            self.data_entry.insert(0, str(self.defaults[0]))
            self.desc_entry.insert(0, self.defaults[1])
        
        vcmd = (master.register(validate_number), '%S')
        self.data_entry.configure(validate='key', validatecommand=vcmd)

    def buttonbox(self):
        ttk.Button(self, text='OK', width=6, command=self.ok_pressed).pack(side=RIGHT, padx=5, pady=5)
        ttk.Button(self, text='Cancel', width=6, command=self.cancel_pressed).pack(side=RIGHT, padx=5, pady=5)
        self.bind("<Return>", lambda event: self.ok_pressed())
        self.bind("<Escape>", lambda event: self.cancel_pressed())

    def ok_pressed(self):
        data = int('0' + self.data_entry.get())
        if data < 0 or data > 255:
            messagebox.showerror('Data error', 'Invalid data (must be between 0 and 255)')
            return
        
        self.result = {
            'data': data,
            'desc': self.desc_entry.get(),
        }
        self.destroy()

    def cancel_pressed(self):
        self.result = None
        self.destroy()

def edit_entity(root):
    changed = False
    for item in ctx.entity_tree.selection():
        i = ctx.entity_tree.index(item)
        d = EntityDialog(root, 'Edit entity', ctx.entities[i]).result
        if d is None:
            continue
        ctx.entities[i][0] = d['x']
        ctx.entities[i][1] = d['y']
        ctx.entities[i][2] = d['desc']
        ctx.entity_tree.item(item, values=ctx.entities[i][0:3])
        changed = True
    if changed:
        redraw_entities()

def select_entity():
    selection = ctx.entity_tree.selection()
    if len(selection) < 1:
        return
    ctx.entity_data_tree.delete(*ctx.entity_data_tree.get_children())
    i = ctx.entity_tree.index(selection[0])

    for datum in ctx.entities[i][3]:
        ctx.entity_data_tree.insert('', END, values=datum)

def remove_entity():
    for item in ctx.entity_tree.selection():
        i = ctx.entity_tree.index(item)
        del ctx.entities[i]
        ctx.entity_tree.delete(item)
    ctx.entity_data_tree.delete(*ctx.entity_data_tree.get_children())
    redraw_entities()

def add_entity(root, defaults=None):
    if defaults is None:
        defaults = [0, 0, '']
        if ctx.selection is not None:
            defaults[0] = int((ctx.selection[0][0] + ctx.selection[1][0] + 1) / 2 * ctx.tile_width)
            defaults[1] = int((ctx.selection[0][1] + ctx.selection[1][1] + 1) / 2 * ctx.tile_height)

    d = EntityDialog(root, 'Add entity', defaults).result
    if d is None:
        return
    
    entity = [d['x'], d['y'], d['desc'], [[0, ''] for x in range(ctx.entity_size)]]
    if len(ctx.entities) > 0:
        for x in range(ctx.entity_size):
            entity[3][x][1] = ctx.entities[-1][3][x][1]
    ctx.entities.append(entity)
    ctx.entity_tree.insert('', END, values=entity[0:3])
    redraw_entities()

def validate_entity(data):
    if data['x'] < 0 or data['x'] > 65535:
        messagebox.showerror('Data error', 'Invalid X coordinate (must be between 0 and 65535)')
        return False
    
    if data['y'] < 0 or data['y'] > 65535:
        messagebox.showerror('Data error', 'Invalid Y coordinate (must be between 0 and 65535)')
        return False
    
    return True

class EntityDialog(simpledialog.Dialog):
    def __init__(self, parent, title='', data=None):
        self.defaults = data
        super().__init__(parent, title)

    def body(self, master):
        master.pack(expand=True, fill=BOTH, padx=5, pady=5)

        ttk.Label(master, text='X').grid(row=0, column=0, sticky=W, padx=5, pady=5)
        ttk.Label(master, text='Y').grid(row=1, column=0, sticky=W, padx=5, pady=5)
        ttk.Label(master, text='Description').grid(row=2, column=0, sticky=W, padx=5, pady=5)

        self.x_entry = Spinbox(master, from_=0, to=65535)
        self.y_entry = Spinbox(master, from_=0, to=65535)
        self.desc_entry = ttk.Entry(master)

        self.x_entry.grid(row=0, column=1, sticky=EW)
        self.y_entry.grid(row=1, column=1, sticky=EW)
        self.desc_entry.grid(row=2, column=1, sticky=EW)

        if self.defaults is not None:
            self.x_entry.delete(0)
            self.x_entry.insert(0, str(self.defaults[0]))
            self.y_entry.delete(0)
            self.y_entry.insert(0, str(self.defaults[1]))
            self.desc_entry.insert(0, self.defaults[2])

        vcmd = (master.register(validate_number), '%S')
        self.x_entry.configure(validate='key', validatecommand=vcmd)
        self.y_entry.configure(validate='key', validatecommand=vcmd)

    def buttonbox(self):
        ttk.Button(self, text='OK', width=6, command=self.ok_pressed).pack(side=RIGHT, padx=5, pady=5)
        ttk.Button(self, text='Cancel', width=6, command=self.cancel_pressed).pack(side=RIGHT, padx=5, pady=5)
        self.bind("<Return>", lambda event: self.ok_pressed())
        self.bind("<Escape>", lambda event: self.cancel_pressed())

    def ok_pressed(self):
        data = {
            'x': int('0' + self.x_entry.get()),
            'y': int('0' + self.y_entry.get()),
            'desc': self.desc_entry.get(),
        }
        if validate_entity(data):
            self.result = data
            self.destroy()

    def cancel_pressed(self):
        self.result = None
        self.destroy()

def remove_data():
    for item in ctx.data_tree.selection():
        ctx.data_tree.delete(item)

def validate_data(data):
    if data['id'] < 0 or data['id'] > 255:
        messagebox.showerror('Data error', 'Invalid data ID (must be between 0 and 255)')
        return False
    
    if data['data'] < 0 or data['data'] > 255:
        messagebox.showerror('Data error', 'Invalid data (must be between 0 and 255)')
        return False
    
    return True

def add_data(root):
    d = MetadataDialog(root, 'Add data')

    if d.result is None:
        return
    
    ctx.data_tree.insert('', END, values=(d.result['id'], d.result['data'], d.result['desc']))

def edit_data(root):
    for i in ctx.data_tree.selection():
        d = MetadataDialog(root, 'Edit data', ctx.data_tree.item(i)['values'])
        if d.result is None:
            continue
        ctx.data_tree.item(i, values=(d.result['id'], d.result['data'], d.result['desc']))

def data_sort_key(a):
    if a[0].isdecimal():
        return int(a[0])
    return a[0]

def data_sort(col, reverse):
    items = [(ctx.data_tree.set(i, col), i) for i in ctx.data_tree.get_children('')]
    items.sort(key=data_sort_key, reverse=reverse)

    for index, (val, i) in enumerate(items):
        ctx.data_tree.move(i, '', index)
    
    heading = ctx.data_tree.heading(col)
    ctx.data_tree.heading(col, command=lambda col=col: data_sort(col, not reverse))

class MetadataDialog(simpledialog.Dialog):
    def __init__(self, parent, title='', data=None):
        self.defaults = data
        super().__init__(parent, title)

    def body(self, master):
        master.pack(expand=True, fill=BOTH, padx=5, pady=5)

        ttk.Label(master, text='ID').grid(row=0, column=0, sticky=W, padx=5, pady=5)
        ttk.Label(master, text='Value').grid(row=1, column=0, sticky=W, padx=5, pady=5)
        ttk.Label(master, text='Description').grid(row=2, column=0, sticky=W, padx=5, pady=5)

        self.id_entry = Spinbox(master, from_=0, to=255)
        self.data_entry = Spinbox(master, from_=0, to=255)
        self.desc_entry = ttk.Entry(master)

        self.id_entry.grid(row=0, column=1, sticky=EW)
        self.data_entry.grid(row=1, column=1, sticky=EW)
        self.desc_entry.grid(row=2, column=1, sticky=EW)

        if self.defaults is not None:
            self.id_entry.delete(0)
            self.id_entry.insert(0, str(self.defaults[0]))
            self.data_entry.delete(0)
            self.data_entry.insert(0, str(self.defaults[1]))
            self.desc_entry.insert(0, self.defaults[2])

        vcmd = (master.register(validate_number), '%S')
        self.id_entry.configure(validate='key', validatecommand=vcmd)
        self.data_entry.configure(validate='key', validatecommand=vcmd)

    def buttonbox(self):
        ttk.Button(self, text='OK', width=6, command=self.ok_pressed).pack(side=RIGHT, padx=5, pady=5)
        ttk.Button(self, text='Cancel', width=6, command=self.cancel_pressed).pack(side=RIGHT, padx=5, pady=5)
        self.bind("<Return>", lambda event: self.ok_pressed())
        self.bind("<Escape>", lambda event: self.cancel_pressed())

    def ok_pressed(self):
        data = {
            'id': int('0'+self.id_entry.get()),
            'data': int('0'+self.data_entry.get()),
            'desc': self.desc_entry.get(),
        }
        if validate_data(data):
            self.result = data
            self.destroy()

    def cancel_pressed(self):
        self.result = None
        self.destroy()

class PropertiesDialog(simpledialog.Dialog):
    def __init__(self, parent, title='Map properties'):
        super().__init__(parent, title)

    def body(self, master):
        master.pack(expand=True, fill=BOTH)

        ttk.Label(master, text='Map width').grid(row=0, column=0, sticky=SW, padx=5, pady=10)
        ttk.Label(master, text='Map height').grid(row=1, column=0, sticky=SW, padx=5, pady=5)
        ttk.Label(master, text='Entity size').grid(row=2, column=0, sticky=SW, padx=5, pady=5)

        self.width_entry = Spinbox(master, from_=0, to=255)
        self.height_entry = Spinbox(master, from_=0, to=255)
        self.size_entry = Spinbox(master, from_=1, to=16380)

        self.width_entry.delete(0)
        self.width_entry.insert(0, str(ctx.width))
        self.height_entry.delete(0)
        self.height_entry.insert(0, str(ctx.height))
        self.size_entry.delete(0)
        self.size_entry.insert(0, str(ctx.entity_size))

        vcmd = (master.register(validate_number), '%S')
        self.width_entry.configure(validate='key', validatecommand=vcmd)
        self.height_entry.configure(validate='key', validatecommand=vcmd)
        self.size_entry.configure(validate='key', validatecommand=vcmd)

        self.width_entry.grid(row=0, column=1, sticky=EW)
        self.height_entry.grid(row=1, column=1, sticky=EW)
        self.size_entry.grid(row=2, column=1, sticky=EW)

        if len(ctx.tiles) == 0:
            ttk.Label(master, text='Screen mode').grid(row=3, column=0, sticky=SW, padx=5, pady=5)
            ttk.Label(master, text='Tile width').grid(row=4, column=0, sticky=SW, padx=5, pady=5)
            ttk.Label(master, text='Tile height').grid(row=5, column=0, sticky=SW, padx=5, pady=5)

            self.mode_entry = Spinbox(master, from_=0, to=2)
            self.tile_width_entry = Spinbox(master, from_=1, to=384)
            self.tile_height_entry = Spinbox(master, from_=1, to=512)

            self.mode_entry.delete(0)
            self.mode_entry.insert(0, str(ctx.mode))
            self.tile_width_entry.delete(0)
            self.tile_width_entry.insert(0, str(ctx.tile_width))
            self.tile_height_entry.delete(0)
            self.tile_height_entry.insert(0, str(ctx.tile_height))

            self.mode_entry.configure(validate='key', validatecommand=vcmd)
            self.tile_width_entry.configure(validate='key', validatecommand=vcmd)
            self.tile_height_entry.configure(validate='key', validatecommand=vcmd)

            self.mode_entry.grid(row=3, column=1, sticky=EW)
            self.tile_width_entry.grid(row=4, column=1, sticky=EW)
            self.tile_height_entry.grid(row=5, column=1, sticky=EW)

    def buttonbox(self):
        ttk.Button(self, text='OK', width=6, command=self.ok_pressed).pack(side=RIGHT, padx=5, pady=5)
        ttk.Button(self, text='Cancel', width=6, command=self.cancel_pressed).pack(side=RIGHT, padx=5, pady=5)
        self.bind("<Return>", lambda event: self.ok_pressed())
        self.bind("<Escape>", lambda event: self.cancel_pressed())

    def ok_pressed(self):
        new_width = int('0' + self.width_entry.get())
        new_height = int('0' + self.height_entry.get())
        new_size = int('0' + self.size_entry.get())

        if new_width < 0 or new_width > 255:
            messagebox.showerror('Property error', 'Invalid map width (must be 0-255)')
            return
        if new_height < 0 or new_height > 255:
            messagebox.showerror('Property error', 'Invalid map height (must be 0-255)')
            return
        if new_size < 1:
            messagebox.showerror('Property error', 'Invalid entity size (must be greater than 0)')
            return
        
        if len(ctx.tiles) == 0:
            new_mode = int('0' + self.mode_entry.get())
            new_tile_width = int('0' + self.tile_width_entry.get())
            new_tile_height = int('0' + self.tile_height_entry.get())

            if new_mode < 0 or new_mode > 2:
                messagebox.showerror('Property error', 'Invalid screen mode (must be 0, 1 or 2)')
                return
            
            pixels_per_byte = 2 if new_mode == 0 else (4 if new_mode == 1 else 8)
            if new_tile_width % pixels_per_byte != 0 or new_tile_width < 1 or new_tile_height < 1:
                messagebox.showerror('Property error', 'Tile size of %dx%d invalid for mode %d' %
                                    (new_tile_width, new_tile_height, new_mode))
                return
            
            ctx.mode = new_mode
            ctx.tile_width = new_tile_width
            ctx.tile_height = new_tile_height

        if new_width != ctx.width or new_height != ctx.height:
            if new_width == 0 or new_height == 0:
                ctx.reset()
            else:
                new_map = [0 for x in range(new_width * new_height)]
                new_tags = [0 for x in range(new_width * new_height)]
                new_notes = ['' for x in range(new_width * new_height)]
                for y in range(0, min(ctx.height, new_height)):
                    for x in range(0, min(ctx.width, new_width)):
                        i = x * ctx.height + y
                        i2 = x * new_height + y
                        new_map[i2] = ctx.map[i]
                        new_tags[i2] = ctx.tags[i]
                        new_notes[i2] = ctx.notes[i]
                ctx.map = new_map if len(ctx.tiles) > 0 else []
                ctx.tags = new_tags
                ctx.notes = new_notes
                ctx.selection = None
                update_selection()
            ctx.width = new_width
            ctx.height = new_height

        if new_size != ctx.entity_size:
            for entity in ctx.entities:
                if new_size < ctx.entity_size:
                    entity[3] = entity[3][:new_size]
                else:
                    entity[3] = entity[3] + [[0, ''] for x in range(new_size - ctx.entity_size)]
            ctx.entity_size = new_size

            ctx.entity_tree.delete(*ctx.entity_tree.get_children())
            ctx.entity_data_tree.delete(*ctx.entity_data_tree.get_children())
            for entity in ctx.entities:
                ctx.entity_tree.insert('', END, values=(entity[0], entity[1], entity[2]))

        refresh_ui()
        self.destroy()

    def cancel_pressed(self):
        self.destroy()

def draw_entity(entity):
    width_scale = (2 if ctx.mode == 0 else 1) * ctx.zoom
    height_scale = (2 if ctx.mode == 2 else 1) * ctx.zoom
    x = entity[0] * width_scale
    y = entity[1] * height_scale
    r = 4 * ctx.zoom
    ctx.canvas.create_bitmap(x, y, background='red', foreground='white', bitmap='info', tags='entity')
    #ctx.canvas.create_oval(x-r, y-r, x+r, y+r, outline='#5073fc', fill='#50c8fc', width=ctx.zoom, tags='entity')

def redraw_entities():
    ctx.canvas.delete('entity')
    if not ctx.draw_entities:
        return

    for entity in ctx.entities:
        draw_entity(entity)

def redraw_grid():
    ctx.canvas.delete('grid')
    if not ctx.draw_grid:
        return
    
    width_scale = (2 if ctx.mode == 0 else 1) * ctx.zoom
    height_scale = (2 if ctx.mode == 2 else 1) * ctx.zoom
    dash = (2, 2)
    for y in range(0, ctx.tile_height * ctx.height, ctx.tile_height):
        ctx.canvas.create_line(0, y * height_scale, ctx.width * ctx.tile_width * width_scale, y * height_scale,
                               dash=dash, tags='grid')
    for x in range(0, ctx.tile_width * ctx.width, ctx.tile_width):
        ctx.canvas.create_line(x * width_scale, 0, x * width_scale, ctx.height * ctx.tile_height * height_scale,
                               dash=dash, tags='grid')

def draw_tile(tile, image, ox, oy):
    for y in range(0, ctx.tile_height):
        for x in range(0, ctx.tile_width):
            image.put(ctx.palette[get_pixel(tile, x, y)], (ox + x, oy + y))

def mix_colours(c1, c2, weight=0.5):
    r = int((int(c1[1:3], 16) * weight + int(c2[1:3], 16) * (1 - weight)))
    g = int((int(c1[3:5], 16) * weight + int(c2[3:5], 16) * (1 - weight)))
    b = int((int(c1[5:7], 16) * weight + int(c2[5:7], 16) * (1 - weight)))
    return '#%02x%02x%02x' % (r, g, b)

def draw_map_tile(x, y):
    i = x * ctx.height + y
    ox = x * ctx.tile_width
    oy = y * ctx.tile_height
    mix = ''

    if ctx.draw_tags and ctx.tags[i] != 0:
        ci1 = math.floor(ctx.tags[i] / 255.0 * (len(TAG_PALETTE)-1))
        ci2 = math.ceil(ctx.tags[i] / 255.0 * (len(TAG_PALETTE)-1))
        c1 = TAG_PALETTE[ci1]
        c2 = TAG_PALETTE[ci2]
        weight = 1.0 - ((ctx.tags[i] / 255.0) - int(ctx.tags[i] / 255.0))
        mix = mix_colours(c1, c2, weight)

    for y in range(0, ctx.tile_height):
        for x in range(0, ctx.tile_width):
            c = ctx.palette[get_pixel(ctx.tiles[ctx.map[i]], x, y)]
            if ctx.draw_tags and ctx.tags[i] != 0:
                c = mix_colours(c, mix, 0.3)
            ctx.canvas.image.put(c, (ox + x, oy + y))

def redraw_map():
    ctx.canvas.delete('image')
    if len(ctx.tiles) == 0:
        ctx.canvas.image = None
        return
    
    img = PhotoImage(width=ctx.tile_width * ctx.width, height=ctx.tile_height * ctx.height)
    ctx.canvas.image = img
    for x in range(0, ctx.width):
        for y in range(0, ctx.height):
            draw_map_tile(x, y)
    if ctx.mode == 0:
        img = img.zoom(2, 1)
    elif ctx.mode == 2:
        img = img.zoom(1, 2)
    ctx.canvas.img = img
    adjust_zoom(0, True)

def redraw_tiles():
    ctx.tiles_canvas.delete('all')

    width_scale = 4 if ctx.mode == 0 else 2 if ctx.mode == 2 else 1
    height_scale = 2

    padded_tile_width = (ctx.tile_width * width_scale)+2
    padded_tile_height = (ctx.tile_height * height_scale)+2
    width = padded_tile_width * (len(ctx.tiles) // 2) + 2
    height = padded_tile_height * 2 + 2

    ctx.tiles_canvas.config(scrollregion=(0, 0, width, height))
    ctx.main_frame.grid_rowconfigure(1, minsize=height + 16) # TODO: 16 - we should get the scrollbar height...

    column = 0
    row = 0
    index = 0
    ctx.tiles_canvas.images = []
    for tile in ctx.tiles:
        img = PhotoImage(width=ctx.tile_width, height=ctx.tile_height)
        draw_tile(tile, img, 0, 0)
        img = img.zoom(width_scale, height_scale)

        ctx.tiles_canvas.create_image((2 + (column * padded_tile_width), 2 + (row * padded_tile_height)), image=img, anchor=NW, tags=[str(index)])
        ctx.tiles_canvas.images.append(img)

        index += 1
        row += 1
        if row == 2:
            row = 0
            column += 1

def toggle_grid():
    ctx.draw_grid = not ctx.draw_grid
    redraw_grid()

def toggle_tags():
    ctx.draw_tags = not ctx.draw_tags
    redraw_map()

def toggle_entities():
    ctx.draw_entities = not ctx.draw_entities
    redraw_entities()

class ImportDialog(simpledialog.Dialog):
    def __init__(self, parent, title):
        self.result = None
        super().__init__(parent, title)

    def body(self, master):
        master.pack(expand=True, fill=BOTH)

        ttk.Label(master, text='Screen mode').grid(row=0, column=0, sticky=SW, padx=5, pady=10)
        ttk.Label(master, text='Tile width').grid(row=1, column=0, sticky=SW, padx=5, pady=5)
        ttk.Label(master, text='Tile height').grid(row=2, column=0, sticky=SW, padx=5, pady=5)

        self.modeEntry = Spinbox(master, from_=0, to=2)
        self.tileWidthEntry = Spinbox(master, from_=1, to=384)
        self.tileHeightEntry = Spinbox(master, from_=1, to=512)

        self.modeEntry.grid(row=0, column=1, sticky=EW)
        self.tileWidthEntry.grid(row=1, column=1, sticky=EW)
        self.tileHeightEntry.grid(row=2, column=1, sticky=EW)

        # Populate default values
        self.modeEntry.delete(0)
        self.modeEntry.insert(0, '0')
        self.tileWidthEntry.delete(0)
        self.tileWidthEntry.insert(0, '8')
        self.tileHeightEntry.delete(0)
        self.tileHeightEntry.insert(0, '16')

        vcmd = (master.register(validate_number), '%S')
        self.modeEntry.configure(validate='key', validatecommand=vcmd)
        self.tileWidthEntry.configure(validate='key', validatecommand=vcmd)
        self.tileHeightEntry.configure(validate='key', validatecommand=vcmd)
    
    def buttonbox(self):
        ttk.Button(self, text='OK', width=6, command=self.ok_pressed).pack(side=RIGHT, padx=5, pady=5)
        ttk.Button(self, text='Cancel', width=6, command=self.destroy).pack(side=RIGHT, padx=5, pady=5)
        self.bind("<Return>", lambda event: self.ok_pressed())
    
    def ok_pressed(self):
        mode = int('0'+self.modeEntry.get())
        tile_width = int('0' + self.tileWidthEntry.get())
        tile_height = int('0' + self.tileHeightEntry.get())
        if mode < 0 or mode > 2:
            messagebox.showerror('Import error', 'Invalid screen mode (must be 0, 1 or 2)')
            return
        
        pixels_per_byte = 2 if mode == 0 else (4 if mode == 1 else 8)

        if tile_width % pixels_per_byte != 0 or tile_width < 1 or tile_height < 1:
            messagebox.showerror('Import error', 'Tile size of %dx%d invalid for mode %d' %
                                (tile_width, tile_height, mode))
            return
    
        self.result = {
            'mode': mode,
            'tile_width': tile_width,
            'tile_height': tile_height,
        }
        self.destroy()

def validate_png(read, scanlines, mode, tile_width, tile_height):
    width = read[0]
    height = read[1]
    info = read[3]

    if 'palette' not in info:
        messagebox.showerror('Import error', 'PNG file is not palettised.')
        return False
    
    max_colours = 16 if mode == 0 else (4 if mode == 1 else 2)

    palette = info['palette']
    if len(palette) > max_colours:
        # Check if any of the extra colours are referenced
        for line in scanlines:
            for col in range(0, width):
                if line[col] >= max_colours:
                    messagebox.showerror('Import error', 'PNG contains too many colours for mode %d (%d > 16)' % (mode, len(palette)))
                    return False
    
    if width % tile_width != 0 or height % tile_height != 0:
        messagebox.showerror('Import error', 'Invalid tile size of %dx%d for image size of %dx%d' %
                             (tile_width, tile_height, width, height))
        return False
    
    return True

def import_file(root):
    filetypes = [('PNG files', '*.png')]
    filename = filedialog.askopenfilename(title='Import map image', filetypes=filetypes)
    if filename == '':
        return
    
    options = ImportDialog(root, 'Map properties').result
    if options is None:
        return

    input = png.Reader(filename=filename).read()
    scanlines = list(input[2])
    if not validate_png(input, scanlines, options['mode'], options['tile_width'], options['tile_height']):
        return
    
    max_colours = 16 if options['mode'] == 0 else (4 if options['mode'] == 1 else 2)
    pixels_per_byte = 2 if options['mode'] == 0 else (4 if options['mode'] == 1 else 8)

    # Validation success, actually import map
    width = input[0]
    height = input[1]
    info = input[3]
    palette = info['palette'][0:max_colours]
    
    ctx.name = None
    ctx.mode = options['mode']
    ctx.tile_width = options['tile_width']
    ctx.tile_height = options['tile_height']
    ctx.width = int(width / options['tile_width'])
    ctx.height = int(height / options['tile_height'])

    # Convert colours to hex codes
    ctx.palette = ['#%02x%02x%02x' % c for c in palette]
    for __unused_color__ in range(len(palette), max_colours):
        ctx.palette.append('#000000')

    # Build tile map and unique tiles list
    ctx.tiles = collections.OrderedDict()
    ctx.map = []

    for col in range(0, width, ctx.tile_width):
        for row in range(0, height, ctx.tile_height):
            tile = []
            for scanline in scanlines[row:row+ctx.tile_height]:
                for offset in range(col, col+ctx.tile_width, pixels_per_byte):
                    tile.append(get_byte(scanline, offset, ctx.mode))
            tile = bytes(tile)
            if tile in ctx.tiles:
                ctx.map.append(ctx.tiles[tile])
            else:
                ctx.map.append(len(ctx.tiles))
                ctx.tiles[tile] = len(ctx.tiles)

    ctx.tiles = list(ctx.tiles.keys())
    ctx.tags = [0 for x in range(ctx.width * ctx.height)]
    ctx.notes = ['' for x in range(ctx.width * ctx.height)]
    ctx.data_tree.delete(*ctx.data_tree.get_children())
    ctx.entities = []
    ctx.entity_tree.delete(*ctx.entity_tree.get_children())
    ctx.entity_data_tree.delete(*ctx.entity_data_tree.get_children())

    refresh_ui()

def import_tiles(root):
    filetypes = [('PNG files', '*.png')]
    filename = filedialog.askopenfilename(title='Import tiles from image', filetypes=filetypes)
    if filename == '':
        return

    input = png.Reader(filename=filename).read()
    if not validate_png(input, ctx.mode, ctx.tile_width, ctx.tile_height):
        return

    width = input[0]
    height = input[1]
    reader = input[2]
    pixels_per_byte = 2 if ctx.mode == 0 else (4 if ctx.mode == 1 else 8)

    if len(ctx.tiles) == 0:
        palette = input[3]['palette']
        max_colours = 16 if ctx.mode == 0 else (4 if ctx.mode == 1 else 2)
        ctx.palette = ['#%02x%02x%02x' % c for c in palette]
        for __unused_color__ in range(len(palette), max_colours):
            ctx.palette.append('#000000')

    # Add new tiles (TODO: Share code with import_file)
    scanlines = list(reader)
    for col in range(0, width, ctx.tile_width):
        for row in range(0, height, ctx.tile_height):
            tile = []
            for scanline in scanlines[row:row+ctx.tile_height]:
                for offset in range(col, col+ctx.tile_width, pixels_per_byte):
                    tile.append(get_byte(scanline, offset, ctx.mode))
            tile = bytes(tile)
            if tile not in ctx.tiles:
                ctx.tiles.append(tile)
    
    if len(ctx.map) != ctx.width * ctx.height:
        ctx.map = [0 for i in range(ctx.width * ctx.height)]
        refresh_ui()
    else:
        redraw_tiles()

class ExportBinaryDialog(simpledialog.Dialog):
    def __init__(self, parent):
        self.result = None
        super().__init__(parent, 'Export binary data')

    def export_map_cb(self):
        for radio in self.map_radios:
            radio.configure(state=NORMAL if self.export_map.get() == 1 or self.export_tags.get() == 1 else DISABLED)

    def body(self, master):
        master.pack(expand=True, fill=BOTH)

        self.export_map = IntVar()
        ttk.Checkbutton(master, text='Export map', variable=self.export_map, command=self.export_map_cb).grid(row=0, column=0, sticky=W)
        self.export_tags = IntVar()
        ttk.Checkbutton(master, text='Export tags', variable=self.export_tags, command=self.export_map_cb).grid(row=1, column=0, sticky=W)
        self.is_row_major = IntVar()
        self.map_radios = [Radiobutton(master, text='Column-major', value=0, variable=self.is_row_major, state=DISABLED)]
        self.map_radios[0].grid(row=2, column=0, sticky=W)
        self.map_radios.append(Radiobutton(master, text='Row-major', value=1, variable=self.is_row_major, state=DISABLED))
        self.map_radios[1].grid(row=3, column=0, sticky=W)
        self.export_tiles = IntVar()
        ttk.Checkbutton(master, text='Export tiles', variable=self.export_tiles).grid(row=4, column=0, sticky=W)
        self.export_entities = IntVar()
        ttk.Checkbutton(master, text='Export entities', variable=self.export_entities).grid(row=5, column=0, sticky=W)
        self.export_data = IntVar()
        ttk.Checkbutton(master, text='Export data', variable=self.export_data).grid(row=6, column=0, sticky=W)
        self.export_palette = IntVar()
        ttk.Checkbutton(master, text='Export palette', variable=self.export_palette).grid(row=7, column=0, sticky=W)
    
    def buttonbox(self):
        ttk.Button(self, text='OK', width=6, command=self.ok_pressed).pack(side=RIGHT, padx=5, pady=5)
        ttk.Button(self, text='Cancel', width=6, command=self.destroy).pack(side=RIGHT, padx=5, pady=5)
        self.bind("<Return>", lambda event: self.ok_pressed())
    
    def ok_pressed(self):
        self.result = {
            'export_map': self.export_map.get() == 1,
            'export_tags': self.export_tags.get() == 1,
            'row_major': self.is_row_major.get() == 1,
            'export_tiles': self.export_tiles.get() == 1,
            'export_entities': self.export_entities.get() == 1,
            'export_data': self.export_data.get() == 1,
            'export_palette': self.export_palette.get() == 1,
        }
        self.destroy()

def export_binaries(root):
    options = ExportBinaryDialog(root).result
    if options is None:
        return
    
    filetypes = [('BIN files', '*.bin')]
    
    if options['export_map']:
        if ctx.width == 0 or ctx.height == 0:
            messagebox.showerror('Export binaries', 'Map is incomplete')
        else:
            filename = filedialog.asksaveasfilename(title='Save map binary', filetypes=filetypes, defaultextension='bin')
            if filename != '':
                with open(filename, 'wb') as file:
                    for i in range(ctx.width * ctx.height):
                        idx = ((i % ctx.height) * ctx.width + (i // ctx.width)) if options['row_major'] else i
                        file.write(ctx.map[idx].to_bytes(1, 'little'))
    
    if options['export_tags']:
        if ctx.width == 0 or ctx.height == 0:
            messagebox.showerror('Export binaries', 'Map is incomplete')
        else:
            filename = filedialog.asksaveasfilename(title='Save map tags binary', filetypes=filetypes, defaultextension='bin')
            if filename != '':
                with open(filename, 'wb') as file:
                    for i in range(ctx.width * ctx.height):
                        idx = ((i % ctx.height) * ctx.width + (i // ctx.width)) if options['row_major'] else i
                        file.write(ctx.tags[idx].to_bytes(1, 'little'))
    
    if options['export_tiles']:
        if len(ctx.tiles) < 1:
            messagebox.showinfo('Export binaries', 'No tiles to export')
        else:
            filename = filedialog.asksaveasfilename(title='Save tiles binary', filetypes=filetypes, defaultextension='bin')
            if filename != '':
                with open(filename, 'wb') as file:
                    for tile in ctx.tiles:
                        file.write(tile)
    
    if options['export_entities']:
        if len(ctx.entities) < 1:
            messagebox.showinfo('Export binaries', 'No entities to export')
        else:
            filename = filedialog.asksaveasfilename(title='Save entities binary', filetypes=filetypes, defaultextension='bin')
            if filename != '':
                with open(filename, 'wb') as file:
                    for e in ctx.entities:
                        file.write(struct.pack('<H', e[0])) # x
                        file.write(struct.pack('<H', e[1])) # y
                        for d in e[3]: # data
                            file.write(d[0].to_bytes(1, 'little'))
    
    if options['export_data']:
        data = []
        for datum in ctx.data_tree.get_children():
            data.append(ctx.data_tree.item(datum)['values'])
        if len(data) < 1:
            messagebox.showinfo('Export binaries', 'No data to export')
        else:
            filename = filedialog.asksaveasfilename(title='Save data binary', filetypes=filetypes, defaultextension='bin')
            if filename != '':
                with open(filename, 'wb') as file:
                    for d in data:
                        file.write(int(d[0]).to_bytes(1, 'little')) # id
                        file.write(int(d[1]).to_bytes(1, 'little')) # value
    
    if options['export_palette']:
        if len(ctx.palette) < 1:
            messagebox.showinfo('Export binaries', 'No palette to export')
        else:
            filename = filedialog.asksaveasfilename(title='Save palette binary', filetypes=filetypes, defaultextension='bin')
            if filename != '':
                with open(filename, 'wb') as file:
                    for c in ctx.palette:
                        # TODO: Offer more colour formats than just 12-bit Plus colours
                        colour = int(c[3] + c[1] + c[5], 16)
                        file.write(struct.pack('<H', colour))

def export_image(root):
    if len(ctx.tiles) < 1 or ctx.width == 0 or ctx.height == 0:
        messagebox.showerror('Export image', 'No valid map image to export')
        return
    filetypes = [('PNG files', '*.png')]
    filename = filedialog.asksaveasfilename(title='Save As...', filetypes=filetypes, defaultextension='png')
    if filename == '':
        return
    if pathlib.Path(filename).suffix != '.png':
        filename = filename + '.png'

    palette = []
    for c in ctx.palette:
        palette.append([int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)])
    rows = [[] for __x in range(ctx.height * ctx.tile_height)]
    for y in range(ctx.height):
        for x in range(ctx.width):
            i = x * ctx.height + y
            for tiley in range(ctx.tile_height):
                for tilex in range(ctx.tile_width):
                    row = y * ctx.tile_height + tiley
                    rows[row].append(get_pixel(ctx.tiles[ctx.map[i]], tilex, tiley))
    output = png.Writer(ctx.width * ctx.tile_width, ctx.height * ctx.tile_height, palette=palette, bitdepth=8)
    with open(filename, 'wb') as imagefile:
        output.write(imagefile, rows)

def open_file(root):
    filetypes = [('MAP files', '*.map')]
    filename = filedialog.askopenfilename(title='Open map', filetypes=filetypes)
    if filename == '':
        return
    with ZipFile(filename, 'r') as mapfile:
        with mapfile.open('map.json') as mapdata:
            ctx.load(mapdata.read().decode())
            ctx.name = filename
            refresh_ui()

def save_file(root, ignore_name = False):
    if ctx.map is None:
        return
    if ctx.name is None or ignore_name is True:
        filetypes = [('MAP files', '*.map')]
        filename = filedialog.asksaveasfilename(title='Save As...', filetypes=filetypes, defaultextension='map')
        if filename == '':
            return
        if pathlib.Path(filename).suffix != '.map':
            filename = filename + '.map'
        ctx.name = filename
    with ZipFile(ctx.name, 'w', compression=zipfile.ZIP_DEFLATED) as mapfile:
        mapfile.writestr('map.json', ctx.toJSON())

def new_file(root):
    if not messagebox.askokcancel('New map', 'This will discard any current work, continue?'):
        return
    ctx.reset()
    refresh_ui()

def refresh_ui():
    redraw_tiles()
    redraw_map()
    redraw_grid()
    redraw_entities()
    update_status()

def main():
    root = Tk()
    root.title('CPC Map editor')
    root.minsize(720, 480)

    # Create menubar
    ctx.menu = Menu(root)
    root.config(menu=ctx.menu)

    # Create menus

    # File menu
    menu = Menu(ctx.menu, tearoff=0)
    menu.add_command(label='New...', underline=0, accelerator='Ctrl+N', command=lambda: new_file(root))
    menu.add_command(label='Open...', underline=0, accelerator='Ctrl+O', command=lambda: open_file(root))
    menu.add_command(label='Save', underline=0, accelerator='Ctrl+S', command=lambda : save_file(root))
    menu.add_command(label='Save As...', underline=5, accelerator='Ctrl+Shift+S', command=lambda : save_file(root, True))
    menu.add_command(label='Properties...', underline=0, accelerator='Ctrl+P', command=lambda: PropertiesDialog(root))
    menu.add_separator()
    menu.add_command(label='Import...', underline=0, accelerator='Ctrl+I', command=lambda : import_file(root))
    menu.add_command(label='Import tiles...', underline=7, accelerator='Ctrl+Shift+I', command=lambda : import_tiles(root))

    # File->Export menu
    export_menu = Menu(menu, tearoff=0)
    export_menu.add_command(label='Export image...', underline=7, accelerator='Ctrl+E', command=lambda: export_image(root))
    export_menu.add_command(label='Export binaries...', underline=7, accelerator='Ctrl+Shift+E', command=lambda: export_binaries(root))
    menu.add_cascade(label='Export', underline=0, menu=export_menu)

    menu.add_separator()
    menu.add_command(label='Exit', underline=1, accelerator='Ctrl+Q', command=root.destroy)

    ctx.menu.add_cascade(label='File', menu=menu)

    # Edit menu
    menu = Menu(ctx.menu, tearoff=0)
    menu.add_command(label='Undo', underline=0, accelerator='Ctrl+Z', state='disabled')
    menu.add_command(label='Redo', underline=0, accelerator='Ctrl+Y', state='disabled')
    menu.add_separator()
    menu.add_command(label='Cut', underline=2, accelerator='Ctrl+X', command=lambda: copy(root, True))
    menu.add_command(label='Copy', underline=0, accelerator='Ctrl+C', command=lambda: copy(root))
    menu.add_command(label='Paste', underline=0, accelerator='Ctrl+V', command=lambda: paste(root))

    ctx.menu.add_cascade(label='Edit', menu=menu)

    # View menu
    menu = Menu(ctx.menu, tearoff=0)
    menu.add_command(label='Zoom out', underline=5, accelerator='Ctrl+-', command=lambda: adjust_zoom(-1))
    menu.add_command(label='Zoom in', underline=5, accelerator='Ctrl+=', command=lambda: adjust_zoom(1))
    menu.add_command(label='Reset zoom', underline=0, accelerator='Ctrl+0', command=lambda: adjust_zoom(-10))
    menu.add_separator()
    menu.add_command(label='Toggle grid', underline=7, accelerator='Ctrl+G', command=lambda: toggle_grid())
    menu.add_command(label='Toggle tags', underline=7, accelerator='Ctrl+T', command=lambda: toggle_tags())
    menu.add_command(label='Toggle entities', underline=7, accelerator='Ctrl+Shift+T', command=lambda: toggle_entities())

    ctx.menu.add_cascade(label='View', menu=menu)

    # Keyboard shortcuts

    root.bind('<Control-i>', lambda e: import_file(root))
    root.bind('<Control-I>', lambda e: import_tiles(root))
    root.bind('<Control-minus>', lambda e: adjust_zoom(-1))
    root.bind('<Control-=>', lambda e: adjust_zoom(1))
    root.bind('<Control-0>', lambda e: adjust_zoom(-10))
    root.bind('<Control-q>', lambda e: root.destroy())
    root.bind('<Control-n>', lambda e: new_file(root))
    root.bind('<Control-o>', lambda e: open_file(root))
    root.bind('<Control-s>', lambda e: save_file(root))
    root.bind('<Control-S>', lambda e: save_file(root, True))
    root.bind('<Control-e>', lambda e: export_image(root))
    root.bind('<Control-E>', lambda e: export_binaries(root))
    root.bind('<Control-g>', lambda e: toggle_grid())
    root.bind('<Control-t>', lambda e: toggle_tags())
    root.bind('<Control-T>', lambda e: toggle_entities())
    root.bind('<Control-p>', lambda e: PropertiesDialog(root))
    root.bind('<Control-x>', lambda e: copy(root, True))
    root.bind('<Control-c>', lambda e: copy(root))
    root.bind('<Control-v>', lambda e: paste(root))

    # Main window layout
    ctx.main_frame = ttk.Frame(root)
    ctx.main_frame.pack(fill=BOTH, expand=True)

    main_pane = ttk.PanedWindow(ctx.main_frame, orient=HORIZONTAL)
    main_pane.grid(column=0, row=0, columnspan=3, sticky=N+E+S+W)

    props_panel = ttk.Frame(main_pane, padding=(10, 10, 0, 10)) # Padding - L, T, R, B
    main_pane.add(props_panel, weight=1)

    mapPanel = ttk.Frame(main_pane)
    main_pane.add(mapPanel, weight=10)

    tiles_panel = ttk.Frame(ctx.main_frame)
    tiles_panel.grid(column=0, row=1, columnspan=3, sticky=N+E+S+W)

    notebook = ttk.Notebook(props_panel)
    notebook.pack(fill=BOTH, expand=True)
    
    props_page = ttk.Frame(notebook, padding=5)
    data_page = ttk.Frame(notebook, padding=5)
    entity_page = ttk.Frame(notebook, padding=5)
    notebook.add(props_page, text='Cell properties')
    notebook.add(entity_page, text='Entities')
    notebook.add(data_page, text='Data')

    # Create cell properties page
    # Cell tag
    cell_tag_group = ttk.LabelFrame(props_page, text='Tag', padding=5)
    cell_tag_group.pack(side=TOP, fill=X)

    ttk.Label(cell_tag_group, text='Value').grid(row=0, column=0, sticky=W, padx=5)
    entry_text = StringVar(value='0')
    vcmd = (root.register(validate_number), '%S')
    entry = Spinbox(cell_tag_group, from_=0, to=255, textvariable=entry_text, validate='key', validatecommand=vcmd)
    ctx.property_widgets.append(entry)
    entry.grid(row=0, column=1, columnspan=8, sticky=EW)
    hex1_text = StringVar(value='0')
    hex2_text = StringVar(value='0')
    hex_text = (hex1_text, hex2_text)
    ttk.Label(cell_tag_group, textvariable=hex1_text).grid(row=2, column=1, columnspan=4)
    ttk.Label(cell_tag_group, textvariable=hex2_text).grid(row=2, column=5, columnspan=4)
    binary_buttons = []
    for bit in range(0, 8):
        button_text = StringVar(value='0')
        button = Button(cell_tag_group, textvariable=button_text, width=1, bd=1, bg='white', fg='black')
        button.configure(command=lambda bit=bit : toggle_bit(binary_buttons, 7-bit, entry_text, hex_text))
        button.text = button_text
        button.grid(row=1, column=1+bit, sticky=EW)
        binary_buttons.insert(0, button)
        ctx.property_widgets.append(button)
    entry_text.trace_add('write', lambda _n, _i, _o: number_widgets_update(entry_text, binary_buttons, hex_text))
    ttk.Button(cell_tag_group, text='Apply to similar', command=apply_cell_tag_to_similar).grid(row=3, column=0, columnspan=9, sticky=S, pady=5)
    for col in range(1,10):
        cell_tag_group.grid_columnconfigure(col, weight=1)

    # Cell notes
    cell_notes_group = ttk.LabelFrame(props_page, text='Notes', padding=5)
    cell_notes_group.pack(side=TOP, fill=BOTH, expand=True, pady=(10,0))

    ctx.note_text = Text(cell_notes_group, wrap=WORD, width=0, height=0)
    ctx.note_text.pack(side=TOP, fill=BOTH, expand=True)

    ctx.set_cell_tag = lambda n, d: update_cell_tag(n, d, entry_text)

    # Entity list
    ctx.entity_tree = ttk.Treeview(entity_page, columns=('x', 'y', 'desc'), show='headings', height=8)
    ctx.entity_tree.heading('x', text='X')
    ctx.entity_tree.heading('y', text='Y')
    ctx.entity_tree.heading('desc', text='Description')

    # Calculate default font size for tables
    default_font = font.nametofont('TkDefaultFont')
    min_header_size = default_font.measure('NNNM')

    ctx.entity_tree.column('x', width=min_header_size, stretch=False)
    ctx.entity_tree.column('y', width=min_header_size, stretch=False)
    ctx.entity_tree.column('desc', width=min_header_size, stretch=True)
    ctx.entity_tree.grid(row=0, column=0, columnspan=2, sticky=N+E+S+W)
    ctx.entity_tree.bind('<<TreeviewSelect>>', lambda e: select_entity())
    ctx.entity_tree.bind('<Double-1>', lambda e: edit_entity(root))

    scrollbar = ttk.Scrollbar(entity_page, orient=VERTICAL, command=ctx.entity_tree.yview)
    ctx.entity_tree.configure(yscroll=scrollbar.set)
    scrollbar.grid(row=0, column=2, sticky=NS)

    ctx.entity_data_tree = ttk.Treeview(entity_page, columns=('data', 'desc'), show='headings', height=3)
    ctx.entity_data_tree.heading('data', text='Data')
    ctx.entity_data_tree.heading('desc', text='Description')
    ctx.entity_data_tree.column('data', width=min_header_size, stretch=False)
    ctx.entity_data_tree.column('desc', width=min_header_size, stretch=True)
    ctx.entity_data_tree.grid(row=1, column=0, columnspan=2, pady=5, sticky=N+E+S+W)
    ctx.entity_data_tree.bind('<Double-1>', lambda e: edit_entity_data(root))

    scrollbar = ttk.Scrollbar(entity_page, orient=VERTICAL, command=ctx.entity_data_tree.yview)
    ctx.entity_data_tree.configure(yscroll=scrollbar.set)
    scrollbar.grid(row=1, column=2, sticky=NS)

    button = ttk.Button(entity_page, text='Remove', command=remove_entity)
    button.grid(column=0, row=2, sticky=SE)
    button = ttk.Button(entity_page, text='Add', command=lambda : add_entity(root))
    button.grid(column=1, row=2, sticky=SW)

    entity_page.grid_rowconfigure(0, weight=2)
    entity_page.grid_rowconfigure(1, weight=1)
    entity_page.grid_columnconfigure(0, weight=1)
    entity_page.grid_columnconfigure(1, weight=1)

    # Data
    ctx.data_tree = ttk.Treeview(data_page, columns=('id', 'data', 'desc'), show='headings', height=1)
    ctx.data_tree.heading('id', text='ID', command=lambda: data_sort('id', False))
    ctx.data_tree.heading('data', text='Data', command=lambda: data_sort('data', False))
    ctx.data_tree.heading('desc', text='Description', command=lambda: data_sort('desc', False))
    ctx.data_tree.column('id', width=min_header_size, stretch=False)
    ctx.data_tree.column('data', width=min_header_size, stretch=False)
    ctx.data_tree.column('desc', width=min_header_size, stretch=True)
    ctx.data_tree.grid(row=0, column=0, columnspan=2, sticky=N+E+S+W)
    ctx.data_tree.bind('<Double-1>', lambda e: edit_data(root))

    scrollbar = ttk.Scrollbar(data_page, orient=VERTICAL, command=ctx.data_tree.yview)
    ctx.data_tree.configure(yscroll=scrollbar.set)
    scrollbar.grid(row=0, column=2, sticky=NS)

    button = ttk.Button(data_page, text='Remove', command=remove_data)
    button.grid(column=0, row=1, sticky=SE, pady=(5, 0))
    button = ttk.Button(data_page, text='Add', command=lambda : add_data(root))
    button.grid(column=1, row=1, sticky=SW, pady=(5, 0))

    data_page.grid_rowconfigure(0, weight=1)
    data_page.grid_columnconfigure(0, weight=1)
    data_page.grid_columnconfigure(1, weight=1)

    # Create map canvas
    ctx.canvas = Canvas(mapPanel, width=0, height=0, borderwidth=0, highlightthickness=0)

    hbar = ttk.Scrollbar(mapPanel, orient=HORIZONTAL)
    hbar.pack(side=BOTTOM, fill=X)
    hbar.config(command=ctx.canvas.xview)

    vbar = ttk.Scrollbar(mapPanel, orient=VERTICAL)
    vbar.pack(side=RIGHT, fill=Y)
    vbar.config(command=ctx.canvas.yview)

    ctx.canvas.config(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
    ctx.canvas.pack(side=LEFT, fill=BOTH, expand=True)

    # Hook up events for selection and zooming
    ctx.canvas.bind('<Button-1>', canvas_press)
    ctx.canvas.bind('<Double-1>', lambda e: canvas_alt_press(e, root))
    ctx.canvas.bind('<Button-3>', lambda e: canvas_alt_press(e, root))
    ctx.canvas.bind('<Motion>', canvas_motion)
    ctx.canvas.bind('<ButtonRelease-1>', canvas_release)
    ctx.canvas.bind('<Enter>', canvas_entered)
    ctx.canvas.bind('<Leave>', canvas_left)

    root.bind('<Left>', lambda e: canvas_scroll(root, -1, 0))
    root.bind('<Right>', lambda e: canvas_scroll(root, 1, 0))
    root.bind('<Up>', lambda e: canvas_scroll(root, 0, -1))
    root.bind('<Down>', lambda e: canvas_scroll(root, 0, 1))

    # Create tiles canvas
    ctx.tiles_canvas = Canvas(tiles_panel, width=0, height=0, bg='white', borderwidth=0, highlightthickness=0)

    hbar = ttk.Scrollbar(tiles_panel, orient=HORIZONTAL)
    hbar.pack(side=BOTTOM, fill=X)
    hbar.config(command=ctx.tiles_canvas.xview)

    ctx.tiles_canvas.config(xscrollcommand=hbar.set)
    ctx.tiles_canvas.pack(side=LEFT, fill=BOTH, expand=True)

    # Hook up click for tile selection
    ctx.tiles_canvas.bind('<Button-1>', tiles_canvas_clicked)
    ctx.tiles_canvas.bind('<Button-3>', tiles_canvas_alt_clicked)

    # Create status bar
    ctx.status_left = StringVar()
    ttk.Label(ctx.main_frame, textvariable=ctx.status_left).grid(row=2, column=0, sticky=W)
    ctx.status_right = StringVar()
    ttk.Label(ctx.main_frame, textvariable=ctx.status_right).grid(row=2, column=1, sticky=E)
    ttk.Sizegrip(ctx.main_frame).grid(row=2, column=2, sticky=SE)

    # Configure grid weighting
    ctx.main_frame.grid_rowconfigure(0, weight=1)
    ctx.main_frame.grid_rowconfigure(1, weight=0)
    ctx.main_frame.grid_rowconfigure(2, weight=0)
    ctx.main_frame.grid_columnconfigure(0, weight=0)
    ctx.main_frame.grid_columnconfigure(1, weight=1)
    ctx.main_frame.grid_columnconfigure(2, weight=0)

    ctx.reset()
    refresh_ui()
    root.mainloop()


if __name__ == '__main__':
    main()
