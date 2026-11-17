"""Real payloads from a GS1200 (firmware as shipped, November 2026).

Taken from the integration's diagnostics download, which leaves out the
serial-number (0x05) and MAC (0x21) frames. The UGREEN app showed, for both:
AC 50 Hz, U-Turbo on, quiet mode on, audio tones on, child lock off, battery
preservation off, operating mode Standard, DC charging 8 A, low battery
alert 10 %, screen brightness Low, screen off after 1 minute.
"""

# Idle at 78 %, AC off, nothing drawing.
IDLE = {
    0x01: "0000000000000000",
    0x04: "4200450029004d00",
    0x09: "0901f30cf30cf30cf30cf40cf80cf20c641b000000b5504ee0790000",
    0x0B: "0000000000000000",
    0x0C: "0000000000000000000000000000",
    0x0F: "00000000",
    0x10: "02",
    0x11: "02",
    0x12: "00",
    0x13: "00",
    0x14: "02",
    0x15: "01",
    0x16: "010001000000010000000000",
    0x17: "000000000000",
}

# Charging at 240 W at 98 %, AC on feeding 148 W. Child lock on, USB off.
CHARGING = {
    0x01: "0000000000000000",
    0x04: "4700430051004f00",
    0x09: "1401780d820d7f0d7b0d700d7f0d960d641b000300ffff624c9a0000",
    0x0B: "0000f00000009400",
    0x0C: "0000000000000000000000000000",
    0x0F: "f0009400",
    0x10: "02",
    0x11: "02",
    0x12: "00",
    0x13: "00",
    0x14: "02",
    0x15: "01",
    0x16: "010000000000010100010000",
    0x17: "000000000000",
}
