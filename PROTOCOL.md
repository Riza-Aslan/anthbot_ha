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
