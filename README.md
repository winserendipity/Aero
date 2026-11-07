[README.md](https://github.com/user-attachments/files/34525308/README.md)
<p align="center">
  <img src="assets/aero_icon_256.png" alt="Aero logo" width="140">
</p>

<h1 align="center">Aero</h1>

<p align="center">
  <b>A professional photo editor for Instagram &amp; Facebook album carousels.</b><br>
  Seamless multi-slide design, film-look editing and high-quality export, built for Windows.
</p>

<p align="center">
  <img alt="Status" src="https://img.shields.io/badge/status-beta-orange">
  <img alt="Version" src="https://img.shields.io/badge/version-0.0.1--beta-blue">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2011-0078D4">
  <img alt="Language" src="https://img.shields.io/badge/language-Python-3776AB">
  <img alt="UI" src="https://img.shields.io/badge/UI-PySide6%20(Qt)-41CD52">
</p>

> **Beta notice:** Aero is under active development. This is an early beta for testing and feedback, **not for general deployment**. Expect bugs and missing features, save often, and keep a copy of your original photos.

---

## Table of contents

1. [About](#about)
2. [Purpose](#purpose)
3. [Platform and compatibility](#platform-and-compatibility)
4. [Built with](#built-with)
5. [System requirements](#system-requirements)
6. [How Aero helps photographers and creators](#how-aero-helps-photographers-and-creators)
6. [Features](#features)
7. [Getting started](#getting-started)
8. [Documentation](#documentation)
9. [Known limitations (beta)](#known-limitations-beta)
10. [Feedback and bug reports](#feedback-and-bug-reports)
11. [Project status and roadmap](#project-status-and-roadmap)
12. [Credits and license](#credits-and-license)

---

## About

**Aero** is a desktop photo editor made for building **seamless carousel albums**: the swipeable multi-photo posts on Instagram, Facebook and Threads where one picture, one design or one story flows across several slides.

You work on one wide canvas that is cut into slides. A photo, a line of text or a shape can sit across the cut between two slides, and when the post is swiped it lines up perfectly. Aero adds a full photo-editing toolkit on top: film emulation, colour grading, cropping, background tools, collage grids and templates.

## Purpose

Designing a carousel usually means juggling a photo editor, a design tool and a lot of manual measuring to make slides line up. Aero puts that work in one place:

- **Design** the whole carousel as a single canvas, with the slide cuts always visible.
- **Edit** every photo with real photographic tools, not just filters.
- **Export** each slide at full quality, ready to upload.

## Platform and compatibility

| Platform | Status |
| --- | --- |
| **Windows 11 (64-bit)** | Supported. Beta installer available. |
| Windows 10 | Not officially tested. |
| macOS / Linux | Not available yet. |
| Mobile (iOS / Android) | Not available. |

Aero is built and tested for Windows 11 desktop. It does not need a GPU or an internet connection.

## Built with

- **Language:** [Python](https://www.python.org/) 3.10 or newer
- **Interface:** [PySide6](https://doc.qt.io/qtforpython/) (Qt for Python), with a custom dark and light theme
- **Image processing:** [NumPy](https://numpy.org/) and [Pillow](https://python-pillow.org/), with `pillow-heif` for HEIC/HEIF
- **Distribution:** packaged as a standalone Windows installer

---

## System requirements

| | Minimum | Recommended |
| --- | --- | --- |
| **OS** | Windows 11, 64-bit | Windows 11, 64-bit (latest updates) |
| **Processor** | 4 cores, 3.0 GHz (Intel Core i5-8400 / AMD Ryzen 5 2600 or better) | 8+ cores (Intel Core i7-12700 / AMD Ryzen 7 5800X or better) |
| **Memory** | 8 GB RAM | 16 GB RAM (32 GB for 4x image exports) |
| **Graphics** | Any GPU with OpenGL 3.3 / DirectX 11 (for example Intel UHD 620) and up-to-date drivers | Dedicated GPU with 4 GB+ VRAM (NVIDIA GTX 1650 / RTX 3050, AMD RX 6600 or better) |
| **Storage** | 1 GB for the app, plus 2 GB free for exports (HDD works) | SSD, with 20 GB+ free for video exports |
| **Sound card** | Not required | Any Windows audio device (only needed to listen to exported videos) |
| **Display** | 1920 x 1080 | 1920 x 1080 or higher |

**Additional notes**

- These figures are estimates from the app's design, not formal benchmarks. Real speed depends on photo size, number of layers and filters.
- **GPU drawing** is on by default and can be switched off in **File > Settings > General**. If a graphics problem is detected at startup, Aero turns it off automatically.
- Photo filters, video filters and exporting use the **processor** (several cores). The GPU makes panning, zooming and dragging smoother.
- Video export is near-lossless, so files are large and rendering takes time. Plan free disk space accordingly. Video slides are exported at up to 2x (for example 2160 x 2700 px), even when images use a higher resolution, which keeps the encoder to roughly 1 GB of memory.
- Some videos (HEVC / H.265) may need the Microsoft "HEVC Video Extensions" from the Microsoft Store.
- No internet connection is needed to use Aero.

---

## How Aero helps photographers and creators

- **Tell a story across slides.** Run a panorama, a skyline or a long product shot across several slides so it only comes together as the viewer swipes.
- **Give photos a consistent look.** Apply one of 200+ film emulations or your own colour grade, and use the same settings on every photo in a series.
- **Keep your quality.** Export slides at full or higher resolution in lossless formats, with no compression just to save space.
- **Stay non-destructive.** Photo edits, crops and background removal are stored as settings on the layer, so your original image is never overwritten and every change can be adjusted or reset.
- **Move fast.** Start from a ready-made template or collage grid, drop in photos and export.
- **Work with iPhone photos.** HEIC and HEIF files are supported for import and export.
- **Design without a design degree.** Snapping, guides and slide-cut markers keep text and photos aligned and centred.

---

## Features

### Canvas and slides

- Seamless multi-slide canvas with **pink dashed lines marking the slide cuts**.
- Slide size presets: **1080 × 1350 (4:5)**, **1080 × 1080 (1:1)**, **1080 × 1920 (9:16)**, **1080 × 1440 (3:4)** and **1920 × 1080 (16:9)**, plus **Custom Slide Size**.
- Choose the number of slides when you create a project.
- **Canvas background:** solid colour, gradient (with adjustable angle), or **texture** (Paper, Crumpled, Cardboard, Linen, Kraft, Charcoal, Brown Paper, Peach, Wood, Cotton, Black, Black Crumple, Sand, Mocha, Stone and Marble).
- **Full-screen preview** of two neighbouring slides, to check how the swipe will look.
- **Overlay layer:** a tinted layer that covers every slide.
- Smooth, **cursor-aware zoom** (zoom in or out at the mouse position), fit-to-window, and a pasteboard around the canvas.

### Photo editing: Edit Image

Open **Edit Image** (`Ctrl+E`, or right-click a photo) for a full adjustment panel with live preview, number boxes and a Reset button:

- **Light:** Exposure, Brightness, Contrast, Highlights, Shadows.
- **Colour:** Temperature, Tint, Vibrance, Saturation.
- **Detail and texture:** Blur, Sharpen, Grain.
- **Filter strength** and **effect direction** controls for filters that have one.
- **Duotone** with your own shadow and highlight colours.

### Filters and film emulation

More than **230 looks**, searchable and grouped by category:

- **203 film emulations** inspired by real stocks: Negative films (77), Slide films (24), Instant films (23), Vintage films (39), Black &amp; White films (22) and Infrared films (18).
- **Creative filters:**
  - *Color &amp; Tone:* Sepia, Monochrome, Black &amp; White, Duotone, High Contrast, Saturation Boost, Vibrance Boost, Cross Process.
  - *Vintage &amp; Film:* Film Grain, Light Leaks, Vignette, Polaroid, Chromatic Aberration, Daguerreotype.
  - *Blur &amp; Focus:* Bokeh, Tilt-Shift, Motion Blur, Radial Blur (Zoom), Radial Blur (Spin), Glow (Orton).
  - *Artistic:* Glitch / VHS, Halftone, Solarize, Pixelate, Posterize, Infrared.
  - *Classic:* Noir, Warm, Cool, Fade, Vivid.

### Cropping

- **Inline crop** directly on the canvas, with a crop panel.
- **Snapping** to slide edges, centres and sizes, and to other layers.
- **Crop to Frame (keep size)** for exact framing.
- **Fit options:** Fill Height, Fill Width and Fill Width 2× (stretch a photo across two slides).
- Crop is non-destructive and can be reopened and adjusted.

### Background tools

- **Remove Background** (automatic or click-based).
- **Cut Out** with a lasso or polygon selection.
- **Erase / Restore** with an adjustable brush.
- **Reset Background Edits** to bring the original back.

### Text

- Add, move, resize and rotate text anywhere, including across slide cuts.
- Choose **font** and **colour**.
- **Bold, Italic, Underline, Strikethrough.**
- **Alignment:** Left, Center, Right, Justify.
- **Line spacing, indent and outline** controls.
- **Text box modes:** Auto Width or Manual Width.

### Shapes

- **Rectangle, Ellipse and Line.**
- Fill colour, border colour and width, **opacity**, **corner rounding** and **drop shadow**.

### Collage grids

- **26 grid layouts** in a visual picker, from simple 2-up to complex mosaics.
- Defaults are clean: **gap 5, square corners**. Rows, columns, gap and corner radius can be changed per grid (Grid Settings).
- **Fill Grid Cells with Images** to drop in many photos at once.
- **Edit each photo inside a grid** (right-click a cell):
  - **Crop Photo**: the same inline crop as on a slide, with snapping.
  - **Edit Photo**: the full Edit Image options for that photo only.
  - **Replace Photo / Remove Photo / Add Photo Here.**
  - **Add Text in This Cell**: text follows the cell's guides.
  - **Cell Color**, **Make Cell Transparent** and **Reset Cell Color** per cell.
- Hold and drag a photo to **swap or move photos between cells**.
- **Empty cell colour** for the whole grid, with a **Transparent** option and an alpha slider.

### Templates

- **22 ready-made carousel templates** in categories: Photo, Lifestyle, Text, Grid, Business and Product.
- Pick a template, then replace the placeholder photos with your own.

### Layers and arrangement

- Every image, text, shape, grid and video is a layer.
- **Scale, Rotation and Opacity** sliders in the layer panel.
- **Send to Front / Send to Back**, one step at a time.
- **Align to Slide:** Left, Center, Right, Top, Middle, Bottom. **Center in Slide**.
- **Flip** horizontally or vertically. **Duplicate**, **Copy / Paste**, **Delete**.
- **Lock / Unlock** layers to prevent accidental changes (`Ctrl+L`).
- **Smart guides and snapping** that can be turned on or off, plus a toggle for guides.
- **Undo / Redo** (up to 100 steps).

### Video

- **Add Video** (next to **Add Image**, in the toolbar and the Insert menu) puts a video layer on the canvas; it plays in the editor.
- Right-click a video for **Crop Video**, **Trim Video Length**, **Edit Video (Filters)** and **Play / Pause**.
- **Crop Video:** crop on the spot with the same box, snapping and panel as photos.
- **Trim Video Length:** keep only the part of the clip you want, with start and end sliders.
- **Edit Video (Filters):** every Edit Image option works on video: all 230+ filters and film looks, plus exposure, contrast, colour, grain and more.
- **Export:** one Export command saves everything. Slides that contain video are exported as MP4 (full quality, original frame rate and sound; a video can run across several slides), and the other slides as images. All files are numbered in slide order.

### Export: quality first

The **Export** dialog is built around keeping every detail:

- **Formats:** PNG (lossless), JPEG (maximum quality), JFIF (maximum quality), TIFF (lossless), WebP (lossless), HEIC (maximum quality), HEIF (maximum quality) and BMP (uncompressed).
- **Resolution:** **Best detail** (automatic 2× to 4×; HEIC / HEIF stop at 2× because they are very memory-hungry) or a fixed 1× to 4×. Slides with video are always limited to 2× (larger video needs many GB of memory and plays on almost no device).
- **Video encoder:** *Best quality - processor* (default, near-lossless H.264) or *Much faster - graphics card* (NVIDIA NVENC, high quality, hardly any processor use). If the graphics card cannot do it, Aero switches to the processor automatically.
- **Speed:** video filters are computed on several threads at once (a few frames ahead), and the encoder is tuned for speed, so filtered videos export several times faster than before.
- **Progress bar:** one progress window for the whole export, with the current slide, overall percentage and time left. You can cancel at any time.
- **Computer load:** *Balanced* (default) uses about half of your CPU cores at lower priority so the PC stays usable; *Gentle* uses 2 cores; *Fast* uses everything. Aero also checks free memory first and offers a lower resolution if the export would not fit.
- Text, shapes and grid photos are rendered at the export resolution, so fonts stay crisp.
- Each slide is saved as its own numbered file (`slide_01`, `slide_02`, ...) in the folder you choose. Slides with video become `.mp4` files in the same folder.
- Transparent areas are kept in PNG, TIFF and WebP.

### Projects and files

- Start screen with **New Project**, **Open** and **Open Recent**.
- **New Project** dialog: name, location, slide size and number of slides.
- Projects are saved as **`.carousel`** files that keep layers, edits, crops, grids and backgrounds, so you can reopen and keep editing.
- **Save, Save As, Close Project.** Aero asks to save or discard unsaved changes before closing.

### Interface and settings

- Modern **dark and light themes** with an adjustable **accent colour**.
- **Settings** with General (language), Appearance, Version and About (system information) tabs.
- Language list: English, Filipino, Español, Français, Deutsch, Português, Italiano, 日本語, 한국어 and 中文 (简体). *(The language option is present; full translation of the interface is still in progress.)*
- Right-click context menus on every layer type.
- Custom Aero icon.

### Keyboard shortcuts

| Action | Shortcut |
| --- | --- |
| New / Open / Save / Save As | `Ctrl+N` / `Ctrl+O` / `Ctrl+S` / `Ctrl+Shift+S` |
| Close project | `Ctrl+W` |
| Edit Image | `Ctrl+E` |
| Duplicate | `Ctrl+D` |
| Lock / Unlock | `Ctrl+L` |
| Zoom in / out | `Ctrl++` / `Ctrl+-` |
| Fit view | `Ctrl+0` |
| Full-screen preview | `F11` |
| Rotate in 15° steps | Hold `Shift` while rotating |

---

## Getting started

### Install the Windows beta

1. Download **`Aero-Setup-0.0.1-beta.exe`** from the [Releases](../../releases) page.
2. Run the installer and follow the steps.
3. Windows may show a *"Windows protected your PC"* message because the beta installer is not code-signed. Click **More info**, then **Run anyway**.
4. Launch **Aero** from the Start menu or the desktop shortcut.

Aero runs as a normal Windows app: you do not need to install Python or anything else. Requires Windows 11 (64-bit).

---

## Documentation

### Quick start: your first carousel

1. Open Aero and choose **New Project**.
2. Name it, pick a slide size (for example 1080 × 1350) and the number of slides.
3. Click **Add Image** and choose your photos. Drag them into place; drag a photo across a pink dashed line to make it span two slides.
4. Select a photo and press `Ctrl+E` to open **Edit Image**. Choose a film look and adjust exposure, contrast and colour.
5. Add text with **Add Text**, or use **Grids** for a collage layout.
6. Check the result with **Full Screen** (`F11`).
7. Choose **File > Export Slides**, pick a format and **Best detail**, and select a folder.

### Working with the canvas

- **Select** a layer by clicking it. **Move** by dragging. **Resize** with the corner squares. **Rotate** with the round handle (hold `Shift` for 15° steps).
- **Right-click** any layer for its menu: edit, crop, replace, arrange, lock, delete and more.
- **Pink dashed lines** show where slides are cut. Keep important content away from them unless you want it to span two slides.
- **Zoom** with the mouse wheel or the zoom commands (`Ctrl++` / `Ctrl+-`); the zoom centres on your cursor.

### Using grids

1. **Insert > Grid Layouts** (or the **Grids** toolbar button) and pick a layout.
2. **Right-click a cell > Add Photo Here**, or **Fill Grid Cells** to add several photos.
3. Right-click a photo in a cell to **Crop**, **Edit**, **Replace** or **Remove** it.
4. Use **Grid Settings** to change rows, columns, gap, corner radius and the empty-cell colour.

### Using templates

Open **Templates**, filter by category, select one and click **Use Template**. Replace the placeholder photos and text with your own.

### Saving, reopening and exporting

- Save projects as `.carousel` files; reopen from the start screen or **File > Open Recent**.
- **Export Slides** produces one image per slide. The exported size is the slide size multiplied by your resolution choice (for example, 1080 × 1350 at 2× is 2160 × 2700).
- Export folders contain numbered files (`slide_01`, `slide_02`, ...), so slides stay in order when uploading.

---

## Known limitations (beta)

- Windows 11 only for now.
- The beta installer is unsigned, so SmartScreen shows a warning.
- Interface translation for the non-English languages is still in progress.
- Very large photos with many heavy filters can be slow to preview on older computers.
- Expect rough edges: this is the first beta.

## Feedback and bug reports

Beta testers are very welcome. Please [open an issue](../../issues) and include:

- What you did right before the problem happened.
- What you expected, and what happened instead.
- A screenshot, if possible.
- Your Windows version (**File > Settings > About** shows it).

Feature ideas are welcome too.

## Project status and roadmap

Aero is **in beta (0.0.1)**. Current focus:

- Finding and fixing bugs reported by testers.
- Improving performance and the editing workflow.
- Adding more creator features based on feedback.

## Credits and license

Created by **Winserendipity**.

© 2026 Winserendipity. **All rights reserved.** Aero is distributed as a compiled Windows application for beta testing. The source code is not public and may not be copied, redistributed or modified without the author's permission.
