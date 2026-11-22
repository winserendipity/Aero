# Third-party notices

Aero is © 2026 Winserendipity, all rights reserved (see `LICENSE`). Aero is built with the open-source components below.
Each component stays under its own license, which is not changed by Aero's license. The full license texts are available from the
project links and are included with the Python packages and in the installed application's folder.

| Component | Used for | License | Project |
|---|---|---|---|
| PySide6 / Qt for Python (Qt) | Windows, canvas, interface | LGPL-3.0 (Qt is also available under GPL / commercial terms) | https://doc.qt.io/qtforpython-6/ , https://www.qt.io |
| NumPy | Photo filters and image maths | BSD-3-Clause | https://numpy.org |
| Pillow | Image reading and saving | MIT-CMU (HPND) | https://python-pillow.org |
| pillow-heif (with libheif and its codecs) | HEIC / HEIF photos | BSD-3-Clause; the bundled libheif and libde265 are LGPL-3.0, and the bundled x265 encoder is GPL-2.0-or-later | https://github.com/bigcat88/pillow_heif , https://github.com/strukturag/libheif |
| OpenCV (opencv-python) | Video decoding | Apache-2.0 (the bundled FFmpeg is LGPL-2.1+) | https://opencv.org |
| imageio-ffmpeg | Provides the FFmpeg program | BSD-2-Clause | https://github.com/imageio/imageio-ffmpeg |
| FFmpeg (program shipped by imageio-ffmpeg) | Video and audio encoding / muxing | GPL-2.0-or-later or GPL-3.0 (the build includes GPL parts) | https://ffmpeg.org |
| x264 (inside FFmpeg) | H.264 video encoding | GPL-2.0-or-later | https://www.videolan.org/developers/x264.html |
| x265 (inside FFmpeg) | HEVC / H.265 video encoding | GPL-2.0-or-later | https://www.x265.org |
| Python | Runtime | PSF License | https://www.python.org |
| PyInstaller | Packaging the Windows application | GPL-2.0 with the bootloader exception (programs it builds may use any license) | https://pyinstaller.org |
| Inno Setup | Windows installer | Inno Setup License (free to use for distributing applications) | https://jrsoftware.org/isinfo.php |

## Notes

- **FFmpeg, x264 and x265** run as a separate program that Aero starts when you export video. Their source code is available from
  the project links above, and you can ask the author for the exact FFmpeg version Aero ships.
- **Qt / PySide6** is used as separate libraries that are not modified. You may replace them with your own build of the same
  version under the LGPL.
- Video codecs such as H.264 and HEVC may be covered by patents in some countries. The encoders are provided by the projects
  above; check your local rules if you plan to distribute Aero commercially.
- The versions and licenses above describe the components at the time of writing. If you rebuild Aero with different versions,
  check each package's current license.
