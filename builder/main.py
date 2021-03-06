# Copyright 2014-present PlatformIO <contact@platformio.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=redefined-outer-name

import re
from os.path import join
from platformio import util

from SCons.Script import (ARGUMENTS, COMMAND_LINE_TARGETS, AlwaysBuild,
                          Builder, Default, DefaultEnvironment)


def _get_flash_size(env):
    # use board's flash size by default
    board_max_size = int(env.BoardConfig().get("upload.maximum_size", 0))

    # check if user overrides LD Script
    match = re.search(r"\.flash\.(\d+)(m|k).*\.ld", env.GetActualLDScript())
    if match:
        if match.group(2) == "k":
            board_max_size = int(match.group(1)) * 1024
        elif match.group(2) == "m":
            board_max_size = int(match.group(1)) * 1024 * 1024

    return ("%dK" % (board_max_size / 1024) if board_max_size < 1048576
            else "%dM" % (board_max_size / 1048576))


def _get_board_f_flash(env):
    frequency = env.subst("$BOARD_F_FLASH")
    frequency = str(frequency).replace("L", "")
    return int(int(frequency) / 1000000)

def _is_ota(env):
    return env.BoardConfig().get("build.ota", False)


env = DefaultEnvironment()
platform = env.PioPlatform()
config = util.load_project_config()
if _is_ota(env):
    app = config.get("env:" + env["PIOENV"], "app")

env.Replace(
    __get_flash_size=_get_flash_size,
    __get_board_f_flash=_get_board_f_flash,

    AR="xtensa-lx106-elf-ar",
    AS="xtensa-lx106-elf-as",
    CC="xtensa-lx106-elf-gcc",
    CXX="xtensa-lx106-elf-g++",
    GDB="xtensa-lx106-elf-gdb",
    NM="xtensa-lx106-elf-nm",
    OBJCOPY="esptool.exe",
    RANLIB="xtensa-lx106-elf-ranlib",
    SIZETOOL="xtensa-lx106-elf-size",

    ARFLAGS=["rc"],

    ASFLAGS=["-x", "assembler-with-cpp"],

    CFLAGS=[
        "-std=gnu99",
        "-Wpointer-arith",
        "-Wno-implicit-function-declaration",
        "-Wl,-EL",
        "-fno-inline-functions",
        "-nostdlib"
    ],

    CCFLAGS=[
        "-Os",  # optimize for size
        "-mlongcalls",
        "-mtext-section-literals",
        "-falign-functions=4",
        "-U__STRICT_ANSI__",
        "-ffunction-sections",
        "-fdata-sections"
    ],

    CXXFLAGS=[
        "-fno-rtti",
        "-fno-exceptions",
        "-std=c++11"
    ],

    CPPDEFINES=[
        ("F_CPU", "$BOARD_F_CPU"),
        "__ets__",
        "ICACHE_FLASH"
    ],

    LINKFLAGS=[
        "-Os",
        "-nostdlib",
        "-Wl,--no-check-sections",
        "-u", "call_user_start",
        "-u", "_printf_float",
        "-u", "_scanf_float",
        "-Wl,-static",
        "-Wl,--gc-sections"
    ],

    #
    # Packages
    #

    FRAMEWORK_ARDUINOESP8266_DIR=platform.get_package_dir(
        "framework-arduinoespressif8266"),
    SDK_ESP8266_DIR=platform.get_package_dir("sdk-esp8266"),
    NONOS_SDK_ESP8266_DIR=platform.get_package_dir("framework-esp8266-nonos-sdk"),

    #
    # Upload
    #

    UPLOADER="esptool",
    UPLOADEROTA=join(platform.get_package_dir("tool-espotapy") or "",
                     "espota.py"),

    UPLOADERFLAGS=[
        "-cd", "$UPLOAD_RESETMETHOD",
        "-cb", "$UPLOAD_SPEED",
        "-cp", '"$UPLOAD_PORT"'
    ],
    UPLOADEROTAFLAGS=[
        "--debug",
        "--progress",
        "-i", "$UPLOAD_PORT",
        "$UPLOAD_FLAGS"
    ],

    UPLOADCMD='$UPLOADER $UPLOADERFLAGS -cf $SOURCE',
    UPLOADOTACMD='"$PYTHONEXE" "$UPLOADEROTA" $UPLOADEROTAFLAGS -f $SOURCE',

    #
    # Misc
    #

    MKSPIFFSTOOL="mkspiffs",
    SIZEPRINTCMD='$SIZETOOL -B -d $SOURCES',
    ESP8266_NONOS_SDK_GENAPP=join("$NONOS_SDK_ESP8266_DIR", "tools", "gen_appbin.py"),
    ESP8266_NONOS_SDK_BOOTv17=join("$NONOS_SDK_ESP8266_DIR", "bin", "boot_v1.7.bin"),

    PROGSUFFIX=".elf"
)

env.Append(
    ASFLAGS=env.get("CCFLAGS", [])[:]
)

if int(ARGUMENTS.get("PIOVERBOSE", 0)):
    env.Prepend(UPLOADERFLAGS=["-vv"])

# Allow user to override via pre:script
if env.get("PROGNAME", "program") == "program":
    env.Replace(PROGNAME="firmware")

#
# Keep support for old LD Scripts
#

env.Replace(BUILD_FLAGS=[
    f.replace("esp8266.flash", "eagle.flash") if "esp8266.flash" in f else f
    for f in env.get("BUILD_FLAGS", [])
])

#
# SPIFFS
#


def fetch_spiffs_size(env):
    spiffs_re = re.compile(
        r"PROVIDE\s*\(\s*_SPIFFS_(\w+)\s*=\s*(0x[\dA-F]+)\s*\)")
    with open(env.GetActualLDScript()) as f:
        for line in f.readlines():
            match = spiffs_re.search(line)
            if not match:
                continue
            env["SPIFFS_%s" % match.group(1).upper()] = match.group(2)

    assert all([k in env for k in ["SPIFFS_START", "SPIFFS_END", "SPIFFS_PAGE",
                                   "SPIFFS_BLOCK"]])

    # esptool flash starts from 0
    for k in ("SPIFFS_START", "SPIFFS_END"):
        _value = 0
        if int(env[k], 16) < 0x40300000:
            _value = int(env[k], 16) & 0xFFFFF
        elif int(env[k], 16) < 0x411FB000:
            _value = int(env[k], 16) & 0xFFFFFF
            _value -= 0x200000  # correction
        else:
            _value = int(env[k], 16) & 0xFFFFFF
            _value += 0xE00000  # correction

        env[k] = hex(_value)


def __fetch_spiffs_size(target, source, env):
    fetch_spiffs_size(env)
    return (target, source)


env.Append(
    BUILDERS=dict(
        DataToBin=Builder(
            action=env.VerboseAction(" ".join([
                '"$MKSPIFFSTOOL"',
                "-c", "$SOURCES",
                "-p", "${int(SPIFFS_PAGE, 16)}",
                "-b", "${int(SPIFFS_BLOCK, 16)}",
                "-s", "${int(SPIFFS_END, 16) - int(SPIFFS_START, 16)}",
                "$TARGET"
            ]), "Building SPIFFS image from '$SOURCES' directory to $TARGET"),
            emitter=__fetch_spiffs_size,
            source_factory=env.Dir,
            suffix=".bin"
        )
    )
)

if "uploadfs" in COMMAND_LINE_TARGETS:
    env.Append(
        UPLOADERFLAGS=["-ca", "$SPIFFS_START"],
        UPLOADEROTAFLAGS=["-s"]
    )

#
# Framework and SDK specific configuration
#

if env.subst("$PIOFRAMEWORK") in ("arduino", "simba"):
    env.Append(
        BUILDERS=dict(
            ElfToBin=Builder(
                action=env.VerboseAction(" ".join([
                    '"$OBJCOPY"',
                    "-eo",
                    '"%s"' % join("$FRAMEWORK_ARDUINOESP8266_DIR",
                                  "bootloaders", "eboot", "eboot.elf"),
                    "-bo", "$TARGET",
                    "-bm", "$BOARD_FLASH_MODE",
                    "-bf", "${__get_board_f_flash(__env__)}",
                    "-bz", "${__get_flash_size(__env__)}",
                    "-bs", ".text",
                    "-bp", "4096",
                    "-ec",
                    "-eo", "$SOURCES",
                    "-bs", ".irom0.text",
                    "-bs", ".text",
                    "-bs", ".data",
                    "-bs", ".rodata",
                    "-bc", "-ec"
                ]), "Building $TARGET"),
                suffix=".bin"
            )
        )
    )

    # Handle uploading via OTA
    ota_port = None
    if env.get("UPLOAD_PORT"):
        ota_port = re.match(
            r"\"?((([0-9]{1,3}\.){3}[0-9]{1,3})|[^\\/]+\.[^\\/]+)\"?$",
            env.get("UPLOAD_PORT"))
    if ota_port:
        env.Replace(UPLOADCMD="$UPLOADOTACMD")

else:
    upload_address = None
    if env.subst("$PIOFRAMEWORK") == "esp8266-rtos-sdk":
        env.Replace(
            UPLOAD_ADDRESS="0x20000",
        )

    # Configure NONOS SDK
    elif env.subst("$PIOFRAMEWORK") == "esp8266-nonos-sdk":
        env.Append(
            CPPPATH=[
                join("$SDK_ESP8266_DIR", "include"), "$PROJECTSRC_DIR"
            ],
            CCFLAGS=[
                "-fno-builtin-printf",
            ]
        )
        if _is_ota(env):
            env.Append(
                BUILDERS=dict(
                    GenSym=Builder(
                        action=env.VerboseAction("$NM -g $SOURCE > $TARGET", "Generating symbols: $TARGET"),
                        suffix=".sym"
                    ),
                    GenApp=Builder(
                        action=env.VerboseAction(" ".join([
                            "$ESP8266_NONOS_SDK_GENAPP",
                            "$SOURCES",
                            "$TARGET",
                            "2",
                            "2",
                            "0",
                            "2",
                            app
                        ]), "Generating OTA bin: $TARGET"),
                        suffix=".bin"
                    )
                )
            )
            env.Replace(
                UPLOAD_ADDRESS="0x1000",
            )
        else:
            env.Replace(
                UPLOAD_ADDRESS="0x10000",
            )

    # Configure Native SDK
    else:
        env.Append(
            CPPPATH=[
                join("$SDK_ESP8266_DIR", "include"), "$PROJECTSRC_DIR"
            ],

            LIBPATH=[
                join("$SDK_ESP8266_DIR", "lib"),
                join("$SDK_ESP8266_DIR", "ld")
            ],
        )
        env.Replace(
            LIBS=[
                "c", "gcc", "phy", "pp", "net80211", "lwip", "wpa", "wpa2",
                "main", "wps", "crypto", "json", "ssl", "pwm", "upgrade",
                "smartconfig", "airkiss", "at"
            ],
            UPLOAD_ADDRESS="0X40000"
        )

    # ESP8266 RTOS SDK and Native SDK common configuration
    if _is_ota(env):
        env.Append(
            BUILDERS=dict(
                ElfToBin=Builder(
                    action=env.VerboseAction(" ".join([
                        '"$OBJCOPY"',
                        "-eo", "$SOURCES",
                        "-es", ".text", "${TARGETS[0]}",
                        "-es", ".data", "${TARGETS[1]}",
                        "-es", ".rodata", "${TARGETS[2]}",
                        "-es", ".irom0.text", "${TARGETS[3]}",
                        "-ec", "-v"
                    ]), "Building $TARGET"),
                    suffix=".bin"
                )
            )
        )
        env.Replace(
            UPLOADER=join(platform.get_package_dir("tool-esptoolpy"), "esptool.py"),
            UPLOADERFLAGS=[
                "--baud", "$UPLOAD_SPEED",
                "--port", "$UPLOAD_PORT",
                "--chip", "esp8266",
                "--after", "no_reset"
            ],
            UPLOADERWRITEFLAGS=[
                "--flash_freq", "${__get_board_f_flash(__env__)}m",
                "--flash_mode", "$BOARD_FLASH_MODE",
                "--flash_size", "${__get_flash_size(__env__)}B",
                "0x00000", "$ESP8266_NONOS_SDK_BOOTv17",
                "$UPLOAD_ADDRESS", "$SOURCE"
            ],
            UPLOADCMD='$UPLOADER $UPLOADERFLAGS write_flash $UPLOADERWRITEFLAGS',
        )
    else:
        env.Append(
            BUILDERS=dict(
                ElfToBin=Builder(
                    action=env.VerboseAction(" ".join([
                        '"$OBJCOPY"',
                        "-eo", "$SOURCES",
                        "-bo", "${TARGETS[0]}",
                        "-bm", "$BOARD_FLASH_MODE",
                        "-bf", "${__get_board_f_flash(__env__)}",
                        "-bz", "${__get_flash_size(__env__)}",
                        "-bs", ".text",
                        "-bs", ".data",
                        "-bs", ".rodata",
                        "-bc", "-ec",
                        "-eo", "$SOURCES",
                        "-es", ".irom0.text", "${TARGETS[1]}",
                        "-ec", "-v"
                    ]), "Building $TARGET"),
                    suffix=".bin"
                )
            )
        )
        env.Replace(
            UPLOADER=join(platform.get_package_dir("tool-esptoolpy"), "esptool.py"),
            UPLOADERFLAGS=[
                "--baud", "$UPLOAD_SPEED",
                "--port", "$UPLOAD_PORT",
                "--chip", "esp8266",
                "--after", "no_reset"
            ],
            UPLOADERWRITEFLAGS=[
                "--flash_freq", "${__get_board_f_flash(__env__)}m",
                "--flash_mode", "$BOARD_FLASH_MODE",
                "--flash_size", "${__get_flash_size(__env__)}B",
                "0x00000", "${SOURCES[0]}",
                "$UPLOAD_ADDRESS", "${SOURCES[1]}"
            ],
            UPLOADCMD='$UPLOADER $UPLOADERFLAGS write_flash $UPLOADERWRITEFLAGS',
        )

#
# Target: Build executable and linkable firmware or SPIFFS image
#

target_elf = env.BuildProgram()
print target_elf
if "nobuild" in COMMAND_LINE_TARGETS:
    if set(["uploadfs", "uploadfsota"]) & set(COMMAND_LINE_TARGETS):
        fetch_spiffs_size(env)
        target_firm = join("$BUILD_DIR", "spiffs.bin")
    elif env.subst("$PIOFRAMEWORK") in ("arduino", "simba"):
        target_firm = join("$BUILD_DIR", "${PROGNAME}.bin")
    else:
        target_firm = [
            join("$BUILD_DIR", "eagle.flash.bin"),
            join("$BUILD_DIR", "eagle.irom0text.bin")
        ]
else:
    if set(["buildfs", "uploadfs", "uploadfsota"]) & set(COMMAND_LINE_TARGETS):
        target_firm = env.DataToBin(
            join("$BUILD_DIR", "spiffs"), "$PROJECTDATA_DIR")
        AlwaysBuild(target_firm)
        AlwaysBuild(env.Alias("buildfs", target_firm))
    else:
        if env.subst("$PIOFRAMEWORK") in ("arduino", "simba"):
            target_firm = env.ElfToBin(
                join("$BUILD_DIR", "${PROGNAME}"), target_elf)
        else:
            if _is_ota(env):
                target_segments = env.ElfToBin([
                    join("$BUILD_DIR", "eagle.app.v6.text.bin"),
                    join("$BUILD_DIR", "eagle.app.v6.data.bin"),
                    join("$BUILD_DIR", "eagle.app.v6.rodata.bin"),
                    join("$BUILD_DIR", "eagle.app.v6.irom0text.bin")
                ], target_elf)
                target_sym = env.GenSym(join("$BUILD_DIR", "eagle.app.sym"), target_elf)
                #env.Depends(target_sym, target_segments)
                target_firm = env.GenApp(join("$BUILD_DIR", "eagle.app.flash.bin"), [target_sym, target_elf, target_segments])
                #env.Depends(target_firm, target_sym)
                #target_firm = target_sym
            else:
                target_firm = env.ElfToBin([
                    join("$BUILD_DIR", "eagle.flash.bin"),
                    join("$BUILD_DIR", "eagle.irom0text.bin")
                ], target_elf)

AlwaysBuild(env.Alias("nobuild", target_firm))
target_buildprog = env.Alias("buildprog", target_firm, target_firm)

#
# Target: Print binary size
#

target_size = env.Alias(
    "size", target_elf,
    env.VerboseAction("$SIZEPRINTCMD", "Calculating size $SOURCE"))
AlwaysBuild(target_size)

#
# Target: Upload firmware or SPIFFS image
#

if not _is_ota(env) or (_is_ota(env) and app == "1"):
    target_upload = env.Alias(
        ["upload", "uploadfs"], target_firm,
        [env.VerboseAction(env.AutodetectUploadPort, "Looking for upload port..."),
         env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE")])
    env.AlwaysBuild(target_upload)
else:
    target_upload = env.Alias(["upload", "uploadfs"], target_firm, env.VerboseAction("echo", "No need to upload user2.bin"))


#
# Default targets
#

Default([target_buildprog, target_size])
