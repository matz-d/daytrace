#!/usr/bin/env python3
"""Spinning ASCII donut animation - based on the classic donut math by Andy Sloane."""
import math, time, sys, os

def render_donut(duration=6):
    A, B = 0.0, 0.0
    try:
        ts = os.get_terminal_size()
        cols = int(ts.columns * 0.6)
        rows = int(ts.lines * 0.6)
    except OSError:
        cols, rows = 48, 20
    half_c, half_r = cols // 2, rows // 2

    end_time = time.time() + duration
    sys.stdout.write("\033[?25l")  # hide cursor

    try:
        while time.time() < end_time:
            output = [[" "] * cols for _ in range(rows)]
            zbuf = [[0.0] * cols for _ in range(rows)]

            for theta_i in range(90):
                theta = theta_i * 0.07
                cos_t, sin_t = math.cos(theta), math.sin(theta)

                for phi_i in range(314):
                    phi = phi_i * 0.02
                    cos_p, sin_p = math.cos(phi), math.sin(phi)
                    cos_A, sin_A = math.cos(A), math.sin(A)
                    cos_B, sin_B = math.cos(B), math.sin(B)

                    cx = cos_t + 2
                    x = cx * (cos_B * cos_p + sin_A * sin_B * sin_p) - sin_B * cos_A
                    y = cx * (sin_B * cos_p - sin_A * cos_B * sin_p) + cos_B * cos_A
                    z = 1.0 / (cx * cos_A * sin_p + sin_A + 5)
                    t = cx * cos_A * sin_p - sin_t * sin_A

                    px = int(half_c + half_c * 0.8 * z * x)
                    py = int(half_r + half_r * 0.6 * z * y)

                    if 0 <= px < cols and 0 <= py < rows:
                        if z > zbuf[py][px]:
                            zbuf[py][px] = z
                            lum = int((t * z * 8))
                            ch = ".,-~:;=!*#$@"[max(0, min(lum, 11))]
                            output[py][px] = f"\033[38;5;{208 + (lum % 5)}m{ch}\033[0m"

            sys.stdout.write("\033[H")
            for row in output:
                sys.stdout.write("".join(row) + "\n")
            sys.stdout.flush()

            A += 0.07
            B += 0.03

    finally:
        sys.stdout.write("\033[?25h")  # show cursor
        sys.stdout.write("\033[0m")

if __name__ == "__main__":
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    render_donut(dur)
