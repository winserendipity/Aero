# Aero 1.0.0 — first public release

Aero is a Windows 11 desktop editor for seamless photo and video carousels on Instagram, Facebook and Threads. 1.0.0 is the first public release. It follows the 0.0.1 beta and brings a redesigned interface, much faster and lighter exporting, per-video sound control and a number of fixes.

**Download:** `Aero-Setup-1.0.0.exe` (Windows 11, 64-bit). Windows SmartScreen may warn about an unsigned installer: click *More info*, then *Run anyway*.

## What's new since the 0.0.1 beta

### New interface
- Redesigned studio-style workspace: slim tool rail on the left, tool options bar under the menu, canvas in the middle, **Properties** and **Layers** docked flush on the right.
- **Properties** names what is selected (Image, Text, Shape, Video, Grid or Canvas) and groups settings into collapsible sections.
- **Layers** panel with search, filter chips (All, Photos, Video, Text, Shapes), thumbnails, lock/visibility icons and a footer with Bring to front, Send to back, Duplicate and Delete.
- Floating view bar for previous/next slide, zoom and fit-to-window.
- New start screen: sidebar, highlighted *New project* card, four-step guide, recent projects and template shortcuts.
- Refreshed dark and light themes with an adjustable accent colour.

### New features
- **Mute per video.** Each video has a *Sound on / Muted* button and right-click entries *Mute this video* and *Sound only from this video*. A muted video adds no sound to the exported slide; Layers shows "Muted". Saved with the project.
- **Video encoder choice on export.** *Best quality – processor* (near-lossless H.264) or *Much faster – graphics card* (NVIDIA NVENC). Aero falls back to the processor if the graphics card cannot be used.
- **Computer load control.** *Balanced*, *Gentle* and *Fast* modes. On Windows, Balanced and Gentle apply a hard CPU ceiling (about 50% / 2 cores' worth) and lower priority, so CPU use and temperatures stay down. The final export message states which limits were applied.

### Faster, lighter exporting
- Video slides export at up to 2× and use far less memory. A HEIC Maximum Quality 4× export with video no longer pushes RAM to the limit.
- Filtered video exports several times faster: filters run on several threads, the colour maths is faster, grain and vignette are calculated once, and clips smaller than the export size are filtered at their real size and enlarged afterwards.
- Photo export no longer pins the CPU at 100%.

### Fixes
- **Trim Video Length:** the up/down arrows on the start and end boxes are now clearly visible, always shown and easier to hit, with a tooltip explaining they change the time by 0.1 s.
- **Readability:** hint text, version and credits lines and other secondary text in Settings and dialogs were too dark on the dark theme. They now follow the theme's muted colour and are readable in both themes.
- Start screen cards no longer collapse after the interface redesign.
- Export memory estimate and guard now account for video slides.

### Version
- The "Beta in testing, not for general deployment" notice is gone. Aero now reads **Aero version 1.0.0** in Settings > Version, on the start screen and in the installer.

## Known limitations
- Windows 11 only.
- Installer is not code-signed.
- Interface translation for non-English languages is still in progress.
- Videos play silently in the editor; sound is added on export.
