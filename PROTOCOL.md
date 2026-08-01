# Anthbot cloud protocol

Reverse-engineered from the official **ANTHBOT+Genie 2.15.6** Android app
(`com.anthbot.genie`, React Native / Hermes bytecode v98, decompiled with
[`hermes-dec`](https://pypi.org/project/hermes-dec/)).

Everything below is taken from the app's own code, not guessed. Where the app
has several code paths for the same command, both are listed.

## Transport

The app talks to AWS IoT Core. Two named Thing shadows are used:

| Shadow name | Purpose |
| --- | --- |
| `property` | Device state — what the mower reports |
| `service`  | Command channel — what the app asks the mower to do |

Commands are published to:

```
$aws/things/{serial_number}/shadow/name/service/update
```

with body:

```json
{"state": {"desired": {"cmd": "<command>", "data": <payload>}}}
```

The app builds this in `publishDeviceCommand(sn, {cmd, data})` and sends it via
the AWS SDK `PublishCommand` (IoT data plane, i.e. a SigV4-signed
`POST /topics/<url-encoded topic>`), so the HTTP path this integration uses is
the same one the app uses.

Responses arrive on `.../shadow/name/service/update/accepted` and
`.../shadow/name/property/update/accepted`. An accepted command echoes
`{"cmd": "<command>", "state": 1}`; `state != 1` means the mower rejected it.

**There is no model-specific branching anywhere in the app's command layer.**
The topic and the `{cmd, data}` envelope are identical for every device. What
differs between product lines is *which* commands a given screen uses — see
below.

## Payload conventions

`data` is **not** uniformly shaped. Each command has its own convention, and
getting it wrong is silently ignored by the firmware:

| Shape | Commands |
| --- | --- |
| bare scalar `0`/`1` | `indoor_switch`, `anti_loss_switch`, `log_switch`, `ctl_rainer` (pion), `ctl_near_chg_mow`, `get_all_props`, `app_state`, `clear_err_code`, `factory_reset` |
| scalar (value) | `mow_delay` |
| `{"<cmd name>": value}` | `light_switch` |
| `{"data": value}` | `anti_loss_radius` |
| `{"volume": value}` | `volume_ctl` |
| `{"switch": v, "continue_time": v}` | `ctl_rainer` (genie) |
| partial object (only changed keys) | `param_set`, `nest_param_set`, `device_config`, `perception_obstacle_ctl` |

## `device_config` — the unified settings command

Newer devices (M-series, the app's `pion` UI tree) expose a `device_config`
object in the **property** shadow and accept a `device_config` **command**
carrying a partial update of the same keys. This is the app's
`useDeviceConfig` hook / `toggleDeviceConfig(sn, data)`.

Keys (read and written identically):

```
log_switch, indoor_switch, rain_switch, rain_continue_time,
anti_loss_switch, anti_loss_radius, pobctl_switch, pobctl_level,
volume, camera_switch
```

The app sends one key per interaction, except rain which sends both together:

```json
{"cmd": "device_config", "data": {"volume": 27}}
{"cmd": "device_config", "data": {"rain_switch": 1, "rain_continue_time": 10800}}
{"cmd": "device_config", "data": {"anti_loss_radius": 30}}
{"cmd": "device_config", "data": {"pobctl_level": 2}}
```

On devices that report a `device_config` object, this is the correct path —
the older per-setting commands (`volume_ctl`, `ctl_rainer`, `indoor_switch`,
`camera_switch`, `anti_loss_*`, `log_switch`, `perception_obstacle_ctl`)
belong to the older `genie` UI tree.

## `param_set` — mowing parameters

Partial update of the `param_set` object in the property shadow:

```
mow_count, mow_mode, cutter_height, mow_head, rid_switch,
enable_adaptive_head, nest_switch, mow_sweep, mow_shred, mow_collect,
restore_default
```

Examples straight from the app:

```json
{"cmd": "param_set", "data": {"cutter_height": 40}}
{"cmd": "param_set", "data": {"mow_head": 90, "enable_adaptive_head": 0}}
{"cmd": "param_set", "data": {"nest_switch": 1}}
```

`enable_adaptive_head = 1` means the mower picks the direction itself;
setting a custom `mow_head` requires `enable_adaptive_head = 0`.

### `ctl_cutter` — a dead end, documented so nobody repeats it

The M-series settings screen contains its own `publishCutterHeightCommand`,
which sends `ctl_cutter` (payload passed straight through, 30 s timeout,
failure message `strCuttingSettingFailed`) instead of `param_set`. That looks
like the M-series has a separate cutting-height command, and the decompiler
emits the modal's save handler as an empty body, so the payload shape cannot
be read out of the bundle.

**It is not needed.** Tested against an M5 (firmware 1.0.124):

| Attempt | Result |
| --- | --- |
| `param_set` `{"cutter_height": 45}` | no effect |
| `ctl_cutter` `45` | no effect |
| `ctl_cutter` `{"cutter_height": 45}` | no effect |
| `param_set` `{"mow_count": 2}` | applied |
| `param_set` `{"cutter_height": 45, "mow_count": 1}` | applied |
| `param_set` `{"cutter_height": 40}` | applied |

The last row is the same payload as the first. The early failures were the
mower not accepting commands at that moment — it reported `online: 0` — not a
wrong command. `param_set` is the correct path for cutting height on the
M-series too.

The wider lesson: a command that appears to do nothing is not evidence that
the payload is wrong. Re-test before concluding, and prefer leaving a command
unimplemented over hardcoding a guess.

## `nest_param_set` — base-station ("nest") mowing

Partial update, keys are **unprefixed** here even though the property shadow
reports them prefixed:

```json
{"cmd": "nest_param_set", "data": {"cutter_height": 40, "mow_count": 2,
                                   "pobctl_switch": 1, "pobctl_level": 1}}
```

Turning nest mowing on/off is *not* part of this command — it is
`param_set` with `nest_switch`.

There is no `set_mow_params` command; that name does not exist in the app.

## The map archive

The lawn geometry is **not** in the shadow. It is a gzipped tar fetched from
`/api/v1/device/v2/presigned_url` with `category=device`, `sub_category=map`
and the filename the app builds in `genZipFilename()`:

```
map_manager_<sn>.tar.gz
```

Note this is *not* `multi_maps.map_list[].map_file_name` — requesting that
returns `NoSuchKey` from S3. The archive members are:

| Member | Contents |
| --- | --- |
| `iot_map.bin` | the mowable lawn, as polygons |
| `iot_bridge.bin` | connections between separate lawn areas |
| `area_setting.json` | zones, no-go areas, ride-on paths |

`area_setting.json` is plain JSON with `custom_areas`, `forbid_areas`,
`region_areas`, `ridable_areas`, `dump_grass_areas` and `remote_forbid_areas`.
Polygon entries carry `vertexs` as `[[x, y], ...]`; `region_areas` carry a
single `x`/`y` seed point.

### Binary layout

Both `.bin` files start with a header whose first byte is its own length:

```
offset  type      iot_map.bin                  iot_bridge.bin
0       uint8     header size (35)             header size (15)
1..2    uint8[2]  version (1, 2)               version (1, 2)
3..4    uint16    total point count            total point count
5..6    uint16    file size                    file size
7..10   uint32    grid width
11..14  uint32    grid height
15..18  float32   resolution, m per cell
19..22  float32   origin x, metres
23..26  float32   origin y, metres
27..34  uint64    map_id                       (at offset 7)
```

The body is a sequence of rings. `iot_map.bin` uses

```
uint32 count, then count * (int32 x, int32 y)
```

and `iot_bridge.bin` prefixes each ring with a one-byte segment id.

**Coordinates are little-endian int32 millimetres**, y pointing up.

### How the units were confirmed

Decoded from a real M5: two rings of 13 points each. Taking the values as
millimetres, their shoelace areas are 14.4 m² and 14.3 m² — 28.8 m² together,
against the 29 m² the shadow reports in `map.map_area`. Each ring closes to
within 50 mm of its start. Centimetres would have given 2880 m².

## `curpath` — the travelled path

The property shadow's `curpath.value` is base64. It decodes to a 22-byte
header followed by 6-byte records:

```
struct { int16 x; int16 y; uint16 flags; }   // little endian, x/y in cm
```

Decoded from a real M5 (`curpath` of 94 bytes → 12 points):

```
  x(cm)   y(cm)   flags
   -102     -23   0x0205
   -102     -22   0x0205
    -91     -23   0x0205
    ...
     -3     -17   0x0205
```

The coordinates are relative to the map origin, in centimetres, and form a
continuous track. `flags` was constant across every sample seen so far, so its
meaning is unknown.

This is enough to plot where the mower has driven, but **not** enough to draw a
map: the lawn boundary is not in the shadow. It lives in a separate binary file
(`multi_maps.map_list[].map_file_name`, e.g. `map_<sn>_0`) fetched through
`/api/v1/device/v2/presigned_url`, whose format has not been analysed. The
app's `downloadMapFile` / `useMap` handle it.

`region_area.points` holds coordinates in the same cm units.

## Full command vocabulary

Device commands found in the app (MQTT protocol verbs such as `publish`,
`subscribe`, `puback` are excluded):

```
algorithm_factory_test  anti_loss_radius   anti_loss_switch   app_state
area_set                auth               ble_state          camera_switch
clean_mode_cmd          clear_err_code     clear_eve_code     clear_rtk_move
ctl_building_border     ctl_building_bridge ctl_building_dump ctl_building_forbid
ctl_cutter              ctl_mapping        ctl_near_chg_mow   ctl_rainer
ctl_rtk_base            custom_area_mow_stop delete_map       delete_sub_map
device_config           distribution_net   exit_remote        factory_reset
factory_resume          get_all_props      indoor_switch      light_switch
local_time              log_switch         log_upload         mow_delay
mow_regular             mow_remote         multi_map_ctl      nest_param_set
ota_start               param_set          perception_obstacle_ctl
pin_input               pincode_reset      remote_ctl         req_all_path
req_bluetooth_file      req_dev_online     req_history_mapping_path
req_rtk_base_info       request_cert       ridable_area_set   robot_maintenance_reset
start_dump              stop_dump          sync_position      voice_set
volume_ctl
```

The app additionally uses a numeric opcode table for the Bluetooth transport
(`mow_start` 64, `mow_pause` 65, `mow_continue` 66, `mow_stop` 67,
`charge_start` 68, …); those numbers are BLE-only and are not used over MQTT.

## Reproducing the analysis

```sh
unzip ANTHBOT+Genie_2.15.6_APKPure.xapk -d xapk
unzip xapk/com.anthbot.genie.apk assets/index.android.bundle -d bundle
pip install hermes-dec
python -m hermes_dec.decompilation.hbc_decompiler \
    bundle/assets/index.android.bundle decompiled.js
grep -oE "\{'cmd': '[a-z0-9_]+'" decompiled.js | sort -u
```

The decompiler emits register-level pseudo-JavaScript, but original function
names are preserved (`publishDeviceCommand`, `useDeviceConfig`,
`toggleMowingParam`, `RainAndSnowGuardScreen`, …), which is what makes the
call sites readable.

Note: the decompiler renders one constant-pool entry incorrectly, so the
string `/assets/app/genie/pages/DeviceHome/images` appears inside every
generator's `{value, done}` return object. It is an artifact — ignore it.
