# LVGL build analysis for the EZVIZ HP5 indoor screen

## Summary

The decrypted `ezapp` executable contains a statically linked copy of LVGL based
on **LVGL v8.1.0**. This identification is high-confidence and is supported by
version-specific diagnostic strings, source-file paths embedded in the binary,
and the v8 API naming scheme.

The application does not load a separate `liblvgl.so`. LVGL, FreeType, LodePNG,
and the QR-code implementation are compiled into the main executable.

The binary may contain private EZVIZ changes, so the most precise conclusion is:

> The LVGL code in `ezapp` is based on upstream LVGL v8.1.0, possibly with
> vendor-specific modifications.

## Analysed artifact

| Property | Value |
|---|---|
| Artifact | Decrypted `firmware/app/app/ezapp` |
| Size | 10,508,504 bytes |
| SHA-256 | `a8ef273c1d60213fcae8ae7567c0d2cb199162bc269766f0cade5e86045a7377` |
| Format | 32-bit little-endian ARM PIE ELF, EABI5 |
| Runtime C library | uClibc |
| Symbol state | Stripped |
| LVGL linkage | Static |

The decrypted executable is not stored in this public repository. The hash
above identifies the exact artifact used for this analysis.

## Version identification

The target matches the upstream [`release/v8.1`](https://github.com/lvgl/lvgl/tree/release/v8.1)
branch, whose `lvgl.h` defines version `8.1.0`. The branch version header is
available at [`lvgl.h`](https://github.com/lvgl/lvgl/blob/release/v8.1/lvgl.h).

Several diagnostics in the executable distinguish this release from adjacent
LVGL versions:

| String found in `ezapp` | Significance |
|---|---|
| `It seems lv_tick_inc() is not called.` | Introduced in the 8.1 series |
| `No display created to so far. No place to assign the new screen` | Present in 8.1; wording changed in 8.2 |
| `Y is %d which is greater than hor. res` | Present in 8.1; corrected in 8.2 |
| `fill_blended: unsupported blend mode` | Present in 8.1 and removed in 8.2 |

The embedded paths `src/core/lv_obj_class.c`, `src/misc/lv_timer.c`, and
`src/lv_api_map.h`, together with symbols such as `lv_disp_drv_register` and
`lv_obj_class_create_obj`, also identify the major API generation as LVGL 8.

## Components present in the final executable

The following list describes code evidenced in the linked `ezapp` image. It is
not a reconstructed copy of the original `lv_conf.h`.

### Core, drawing, HAL, and miscellaneous code

- Display, event, group, input-device, object, object-class, object-position,
  object-style, object-tree, and refresh code
- Display and input-device HAL code
- Animation, color, file-system, memory, style, timer, and text utilities
- Image decoding and caching
- Image, label, mask, rectangle, and blend drawing paths

### Widgets

- Arc
- Button
- Button matrix
- Canvas
- Checkbox
- Dropdown
- Image
- Label
- Roller
- Table
- Text area

### Extra widgets and layouts

- Calendar
- Chart
- Meter
- Message box
- Tile view
- Flex layout

### Optional libraries

- PNG decoding, backed by LodePNG
- BMP decoding
- QR-code generation, backed by `qrcodegen`
- FreeType font rendering

These optional libraries are part of `ezapp`; there are no corresponding
dynamically loaded LVGL, FreeType, or image-decoder shared objects.

The shipped GUI resource descriptors directly use labels, buttons, images, and
the calendar. Their observed `layer_type` counts are:

| Resource layer type | Count |
|---|---:|
| Label | 15 |
| Button | 3 |
| Image | 2 |
| Generic layer | 1 |
| Calendar | 1 |

## Configuration inferred from the binary

| LVGL option or property | Inferred value | Confidence | Evidence |
|---|---:|---|---|
| `LV_COLOR_DEPTH` | `16` | High | RGB565 conversion and framebuffer paths |
| `LV_DRAW_COMPLEX` | `1` | High | Draw-mask, radius/angle mask, and complex blend code |
| `LV_USE_FONT_COMPRESSED` | `0` | High | Compiled warning for compressed fonts being disabled |
| `LV_USE_FONT_SUBPX` | `0` | High | Compiled warning explicitly states that the option is `0` |
| `LV_USE_LOG` | `1` | High | LVGL log formatting and warning diagnostics are present |
| `LV_USE_ASSERT_NULL` | Enabled | Medium | Null-check assertion expressions and assertion reporting |
| `LV_USE_ASSERT_MALLOC` | Enabled | Medium | Allocation-check assertion expressions and reporting |

The exact values of `LV_MEM_CUSTOM`, `LV_MEM_SIZE`, and the image-cache size
cannot be recovered confidently from the current static evidence.

The application uses a 1024 x 600 framebuffer and maps a display buffer to
`/dev/fb0`. This describes the HP5 runtime display integration; it is not by
itself proof of a particular compile-time LVGL macro.

## Runtime fonts

The application references these font files:

- `/home/app/sysres/font/NotoSansJP.ttf`
- `/home/app/sysres/font/custom_symbol.ttf`
- `/home/app/sysres/font/msyh_cut.ttf`
- `/home/app/sysres/font/tstar.ttf`

This is consistent with the statically linked FreeType integration.

## Components not evidenced in the linked image

No direct source-path or distinctive-string evidence was found for these LVGL
v8.1 components:

- Widgets: animation image, color wheel, image button, keyboard, LED, list,
  spinbox, spinner, span, switch, tab view, and window
- Layouts: grid
- Libraries: GIF, SJPG, Rlottie, and snapshot
- Other widgets with no direct evidence: bar, line, and slider

This does **not** prove that their `LV_USE_*` macros were disabled. Because the
binary is stripped, and because linker garbage collection or link-time
optimisation can discard unused functions, a feature enabled during compilation
may still be absent from the final executable.

## Embedded LVGL source paths

The following paths were recovered from the executable:

```text
src/core/lv_disp.c
src/core/lv_event.c
src/core/lv_group.c
src/core/lv_indev.c
src/core/lv_obj.c
src/core/lv_obj_class.c
src/core/lv_obj_pos.c
src/core/lv_obj_style.c
src/core/lv_obj_tree.c
src/core/lv_refr.c
src/draw/../misc/lv_color.h
src/draw/lv_draw_blend.c
src/draw/lv_draw_img.c
src/draw/lv_draw_label.c
src/draw/lv_draw_mask.c
src/draw/lv_draw_rect.c
src/draw/lv_img_buf.c
src/draw/lv_img_cache.c
src/draw/lv_img_decoder.c
src/extra/layouts/flex/lv_flex.c
src/extra/libs/bmp/lv_bmp.c
src/extra/libs/freetype/lv_freetype.c
src/extra/libs/png/lv_png.c
src/extra/libs/qrcode/lv_qrcode.c
src/extra/libs/qrcode/qrcodegen.c
src/extra/widgets/calendar/lv_calendar.c
src/extra/widgets/chart/lv_chart.c
src/extra/widgets/meter/lv_meter.c
src/extra/widgets/msgbox/lv_msgbox.c
src/extra/widgets/tileview/lv_tileview.c
src/font/lv_font.c
src/font/lv_font_fmt_txt.c
src/hal/../draw/../misc/lv_color.h
src/hal/lv_hal_disp.c
src/hal/lv_hal_indev.c
src/lv_api_map.h
src/misc/lv_anim.c
src/misc/lv_color.c
src/misc/lv_fs.c
src/misc/lv_mem.c
src/misc/lv_style.c
src/misc/lv_timer.c
src/misc/lv_txt.c
src/widgets/lv_arc.c
src/widgets/lv_btnmatrix.c
src/widgets/lv_canvas.c
src/widgets/lv_dropdown.c
src/widgets/lv_img.c
src/widgets/lv_label.c
src/widgets/lv_roller.c
src/widgets/lv_table.c
src/widgets/lv_textarea.c
```

## Interpretation notes

Upstream defaults alone cannot describe this build. For example, PNG, BMP,
QR-code, and FreeType support are disabled in the upstream
[`lv_conf_template.h`](https://github.com/lvgl/lvgl/blob/release/v8.1/lv_conf_template.h),
but their implementations are present in the HP5 executable. EZVIZ therefore
used a project-specific LVGL configuration.

The findings above intentionally distinguish three levels of evidence:

1. **Observed:** a path, diagnostic, API name, or resource is present in the
   artifact.
2. **Inferred:** the observed compiled branch strongly indicates a configuration
   value.
3. **Unknown:** the stripped final executable does not preserve enough evidence
   to reconstruct the original setting reliably.
