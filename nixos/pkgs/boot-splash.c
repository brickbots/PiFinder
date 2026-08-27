/*
 * boot-splash - Early boot splash for PiFinder
 *
 * Displays welcome image with Knight Rider animation until stopped.
 * Designed for NixOS early boot (before Python starts).
 *
 * Hardware: SPI0.0, DC=GPIO24, RST=GPIO25. Two panels:
 *   - rev 3 (Pi 4B):  128x128 SSD1351 OLED
 *   - v4    (CM4):    176x176 SSD1333 OLED, mounted 270° (luma rotate=3)
 * The panel is picked from the device-tree model string: a CM4 carrier is
 * a v4 board. That signal is available in early boot / initrd, unlike the
 * BQ25895 charger probe the Python app uses (needs the i2c-gpio bus up).
 */

#include <fcntl.h>
#include <linux/gpio.h>
#include <linux/spi/spidev.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define MAX_DIM 176
#define SPI_DEVICE "/dev/spidev0.0"
#define SPI_SPEED 40000000
#define GPIO_DC 24
#define GPIO_RST 25

/* RGB565 colors (display interprets as RGB despite BGR setting) */
#define COL_BLACK   0x0000
#define COL_RED     0xF800
#define COL_DKRED   0x3800   /* dim red — unfilled progress track */

#define PROGRESS_FILE_DEFAULT "/run/pifinder-boot-progress"

/* Include generated image data (128x128, both panels center it) */
#include "welcome_image.h"
#define IMG_W 128
#define IMG_H 128

enum panel_type { PANEL_SSD1351, PANEL_SSD1333 };

static enum panel_type panel = PANEL_SSD1351;
static int disp_w = 128;
static int disp_h = 128;

static int spi_fd = -1;
static int gpio_fd = -1;
static struct gpio_v2_line_request dc_req;
static struct gpio_v2_line_request rst_req;
/* Logical orientation (matches the Python app's drawing space); the
 * SSD1333's 270° panel mounting is applied at flush time. */
static uint16_t framebuf[MAX_DIM * MAX_DIM];
static volatile int running = 1;

static void signal_handler(int sig) {
    (void)sig;
    running = 0;
}

static void msleep(int ms) {
    struct timespec ts = { .tv_sec = ms / 1000, .tv_nsec = (ms % 1000) * 1000000L };
    nanosleep(&ts, NULL);
}

/* v4 boards are CM4-based; rev 3 is a Pi 4B. Reads the DT model string,
 * which the firmware populates from the board it actually booted on. */
static void detect_panel(void) {
    static const char *paths[] = {
        "/sys/firmware/devicetree/base/model",
        "/proc/device-tree/model",
    };
    char model[128] = {0};

    for (size_t i = 0; i < sizeof(paths) / sizeof(paths[0]); i++) {
        FILE *f = fopen(paths[i], "r");
        if (!f)
            continue;
        size_t n = fread(model, 1, sizeof(model) - 1, f);
        fclose(f);
        model[n] = '\0';
        break;
    }

    if (strstr(model, "Compute Module 4")) {
        panel = PANEL_SSD1333;
        disp_w = 176;
        disp_h = 176;
    }
}

static int gpio_request_line(int chip_fd, int pin, struct gpio_v2_line_request *req) {
    struct gpio_v2_line_request r = {0};
    r.offsets[0] = pin;
    r.num_lines = 1;
    r.config.flags = GPIO_V2_LINE_FLAG_OUTPUT;
    snprintf(r.consumer, sizeof(r.consumer), "boot-splash");

    if (ioctl(chip_fd, GPIO_V2_GET_LINE_IOCTL, &r) < 0) {
        perror("GPIO_V2_GET_LINE_IOCTL");
        return -1;
    }
    *req = r;
    return 0;
}

static void gpio_set(struct gpio_v2_line_request *req, int value) {
    struct gpio_v2_line_values vals = {0};
    vals.bits = value ? 1 : 0;
    vals.mask = 1;
    ioctl(req->fd, GPIO_V2_LINE_SET_VALUES_IOCTL, &vals);
}

static void spi_write(const uint8_t *data, size_t len) {
    const size_t chunk_size = 4096;
    while (len > 0) {
        size_t this_len = len > chunk_size ? chunk_size : len;
        struct spi_ioc_transfer tr = {0};
        tr.tx_buf = (unsigned long)data;
        tr.len = this_len;
        tr.speed_hz = SPI_SPEED;
        tr.bits_per_word = 8;
        ioctl(spi_fd, SPI_IOC_MESSAGE(1), &tr);
        data += this_len;
        len -= this_len;
    }
}

static void oled_cmd(uint8_t cmd) {
    gpio_set(&dc_req, 0);
    spi_write(&cmd, 1);
}

static void oled_data(const uint8_t *data, size_t len) {
    gpio_set(&dc_req, 1);
    spi_write(data, len);
}

static void oled_reset(void) {
    gpio_set(&rst_req, 1);
    msleep(10);
    gpio_set(&rst_req, 0);
    msleep(10);
    gpio_set(&rst_req, 1);
    msleep(10);
}

static void ssd1351_init(void) {
    uint8_t d;

    oled_reset();

    oled_cmd(0xFD); d = 0x12; oled_data(&d, 1); /* Unlock */
    oled_cmd(0xFD); d = 0xB1; oled_data(&d, 1); /* Unlock commands */
    oled_cmd(0xAE); /* Display off */
    oled_cmd(0xB3); d = 0xF1; oled_data(&d, 1); /* Clock divider */
    oled_cmd(0xCA); d = 0x7F; oled_data(&d, 1); /* Mux ratio */

    uint8_t col[2] = {0x00, 0x7F};
    oled_cmd(0x15); oled_data(col, 2); /* Column address */
    uint8_t row[2] = {0x00, 0x7F};
    oled_cmd(0x75); oled_data(row, 2); /* Row address */

    oled_cmd(0xA0); d = 0x74; oled_data(&d, 1); /* BGR, 65k color */
    oled_cmd(0xA1); d = 0x00; oled_data(&d, 1); /* Start line */
    oled_cmd(0xA2); d = 0x00; oled_data(&d, 1); /* Display offset */
    oled_cmd(0xB5); d = 0x00; oled_data(&d, 1); /* GPIO */
    oled_cmd(0xAB); d = 0x01; oled_data(&d, 1); /* Function select */
    oled_cmd(0xB1); d = 0x32; oled_data(&d, 1); /* Precharge */

    uint8_t vsl[3] = {0xA0, 0xB5, 0x55};
    oled_cmd(0xB4); oled_data(vsl, 3); /* VSL */

    oled_cmd(0xBE); d = 0x05; oled_data(&d, 1); /* VCOMH */
    oled_cmd(0xC7); d = 0x0F; oled_data(&d, 1); /* Master contrast */
    oled_cmd(0xB6); d = 0x01; oled_data(&d, 1); /* Precharge2 */
    oled_cmd(0xA6); /* Normal display */

    uint8_t contrast[3] = {0xFF, 0xFF, 0xFF};
    oled_cmd(0xC1); oled_data(contrast, 3); /* Contrast */
}

/* Mirrors PiFinder.ssd1333_device._init_sequence (bgr=True → remap 0x74).
 * Key differences from the SSD1351: MUX 175, no second unlock, no GPIO /
 * Function Select / VSL commands, built-in linear LUT (0xB9). */
static void ssd1333_init(void) {
    uint8_t d;

    oled_reset();

    oled_cmd(0xFD); d = 0x12; oled_data(&d, 1); /* Unlock */
    oled_cmd(0xAE); /* Display off */
    oled_cmd(0xB3); d = 0xF1; oled_data(&d, 1); /* Clock divider */
    oled_cmd(0xCA); d = 0xAF; oled_data(&d, 1); /* Mux ratio = 175 */

    uint8_t col[2] = {0x00, 0xAF};
    oled_cmd(0x15); oled_data(col, 2); /* Column address */
    uint8_t row[2] = {0x00, 0xAF};
    oled_cmd(0x75); oled_data(row, 2); /* Row address */

    oled_cmd(0xA0); d = 0x74; oled_data(&d, 1); /* Remap: 65k color, BGR */
    oled_cmd(0xA1); d = 0x00; oled_data(&d, 1); /* Start line */
    oled_cmd(0xA2); d = 0x00; oled_data(&d, 1); /* Display offset */
    oled_cmd(0xB1); d = 0x32; oled_data(&d, 1); /* Precharge */
    oled_cmd(0xBB); d = 0x17; oled_data(&d, 1); /* Pre-charge voltage */
    oled_cmd(0xBE); d = 0x05; oled_data(&d, 1); /* VCOMH */
    oled_cmd(0xC7); d = 0x0F; oled_data(&d, 1); /* Master contrast */
    oled_cmd(0xB6); d = 0x08; oled_data(&d, 1); /* Precharge2 */
    oled_cmd(0xB9); /* Built-in linear LUT */
    oled_cmd(0xA6); /* Normal display */

    uint8_t contrast[3] = {0xFF, 0xFF, 0xFF};
    oled_cmd(0xC1); oled_data(contrast, 3); /* Contrast */
}

static void oled_flush(void) {
    uint8_t max = (uint8_t)(disp_w - 1);
    uint8_t col[2] = {0x00, max};
    oled_cmd(0x15); oled_data(col, 2);
    uint8_t row[2] = {0x00, max};
    oled_cmd(0x75); oled_data(row, 2);
    oled_cmd(0x5C); /* Write RAM */

    static uint8_t buf[MAX_DIM * MAX_DIM * 2];
    if (panel == PANEL_SSD1333) {
        /* The v4 panel is mounted 270° (the app drives it with luma
         * rotate=3, i.e. the image is rotated 90° CCW before the RAM
         * write): logical (x,y) lands at RAM (y, w-1-x). */
        for (int y = 0; y < disp_h; y++) {
            for (int x = 0; x < disp_w; x++) {
                uint16_t px = framebuf[y * disp_w + x];
                int ram = (disp_w - 1 - x) * disp_w + y;
                buf[ram * 2] = px >> 8;
                buf[ram * 2 + 1] = px & 0xFF;
            }
        }
    } else {
        for (int i = 0; i < disp_w * disp_h; i++) {
            buf[i * 2] = framebuf[i] >> 8;
            buf[i * 2 + 1] = framebuf[i] & 0xFF;
        }
    }
    oled_data(buf, (size_t)disp_w * disp_h * 2);
}

/* Fill the framebuffer with the welcome image, centered (the image is
 * 128x128; the v4 panel is 176x176, leaving a black border). */
static void draw_welcome(void) {
    memset(framebuf, 0, sizeof(uint16_t) * disp_w * disp_h);
    int x0 = (disp_w - IMG_W) / 2;
    int y0 = (disp_h - IMG_H) / 2;
    for (int y = 0; y < IMG_H; y++) {
        memcpy(&framebuf[(y0 + y) * disp_w + x0],
               &welcome_image[y * IMG_W],
               IMG_W * sizeof(uint16_t));
    }
}

static void draw_scanner(int pos, int scanner_width) {
    draw_welcome();

    /* Draw Knight Rider scanner at bottom (last 4 rows) */
    int y_start = disp_h - 4;
    int center = pos;

    for (int x = 0; x < disp_w; x++) {
        int dist = abs(x - center);
        uint16_t color = COL_BLACK;

        if (dist < scanner_width) {
            /* Gradient: brighter at center */
            int intensity = 31 - (dist * 31 / scanner_width);
            if (intensity < 8) intensity = 8;  /* Minimum brightness */
            /* RGB565: RRRRRGGGGGGBBBBB - red is high 5 bits */
            color = ((uint16_t)intensity & 0x1F) << 11;
        }

        for (int y = y_start; y < disp_h; y++) {
            framebuf[y * disp_w + x] = color;
        }
    }

    oled_flush();
}

/* Read a 0-100 percentage from a file. Returns -1 if missing/unparseable. */
static int read_progress(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    int pct = -1;
    if (fscanf(f, "%d", &pct) != 1) pct = -1;
    fclose(f);
    if (pct < 0) return -1;
    if (pct > 100) pct = 100;
    return pct;
}

static void draw_progress(int pct) {
    draw_welcome();

    /* Progress bar across the bottom 4 rows, filling left-to-right.
     * Filled portion bright red, remaining track dim red. */
    int y_start = disp_h - 4;
    int fill = pct * disp_w / 100;

    for (int x = 0; x < disp_w; x++) {
        uint16_t color = (x < fill) ? COL_RED : COL_DKRED;
        for (int y = y_start; y < disp_h; y++) {
            framebuf[y * disp_w + x] = color;
        }
    }

    oled_flush();
}

/* Classic 5x7 bitmap font, A-Z + space + '!'. Each glyph is 5 column bytes,
 * bit 0 = top row. Enough for the watchdog's failure screen; night-vision red
 * like everything else on this display. */
static const uint8_t font5x7[28][5] = {
    {0x7E, 0x11, 0x11, 0x11, 0x7E}, /* A */
    {0x7F, 0x49, 0x49, 0x49, 0x36}, /* B */
    {0x3E, 0x41, 0x41, 0x41, 0x22}, /* C */
    {0x7F, 0x41, 0x41, 0x22, 0x1C}, /* D */
    {0x7F, 0x49, 0x49, 0x49, 0x41}, /* E */
    {0x7F, 0x09, 0x09, 0x09, 0x01}, /* F */
    {0x3E, 0x41, 0x49, 0x49, 0x7A}, /* G */
    {0x7F, 0x08, 0x08, 0x08, 0x7F}, /* H */
    {0x00, 0x41, 0x7F, 0x41, 0x00}, /* I */
    {0x20, 0x40, 0x41, 0x3F, 0x01}, /* J */
    {0x7F, 0x08, 0x14, 0x22, 0x41}, /* K */
    {0x7F, 0x40, 0x40, 0x40, 0x40}, /* L */
    {0x7F, 0x02, 0x0C, 0x02, 0x7F}, /* M */
    {0x7F, 0x04, 0x08, 0x10, 0x7F}, /* N */
    {0x3E, 0x41, 0x41, 0x41, 0x3E}, /* O */
    {0x7F, 0x09, 0x09, 0x09, 0x06}, /* P */
    {0x3E, 0x41, 0x51, 0x21, 0x5E}, /* Q */
    {0x7F, 0x09, 0x19, 0x29, 0x46}, /* R */
    {0x46, 0x49, 0x49, 0x49, 0x31}, /* S */
    {0x01, 0x01, 0x7F, 0x01, 0x01}, /* T */
    {0x3F, 0x40, 0x40, 0x40, 0x3F}, /* U */
    {0x1F, 0x20, 0x40, 0x20, 0x1F}, /* V */
    {0x3F, 0x40, 0x38, 0x40, 0x3F}, /* W */
    {0x63, 0x14, 0x08, 0x14, 0x63}, /* X */
    {0x07, 0x08, 0x70, 0x08, 0x07}, /* Y */
    {0x61, 0x51, 0x49, 0x45, 0x43}, /* Z */
    {0x00, 0x00, 0x00, 0x00, 0x00}, /* space */
    {0x00, 0x00, 0x5F, 0x00, 0x00}, /* ! */
};

static const uint8_t *glyph_for(char c) {
    if (c >= 'a' && c <= 'z') c -= 32;
    if (c >= 'A' && c <= 'Z') return font5x7[c - 'A'];
    if (c == '!') return font5x7[27];
    return font5x7[26]; /* everything else renders as space */
}

static void draw_text_centered(int y, const char *s, int scale, uint16_t color) {
    int len = (int)strlen(s);
    int char_w = 6 * scale; /* 5 columns + 1 spacing */
    int x0 = (disp_w - len * char_w) / 2;
    if (x0 < 0) x0 = 0;

    for (int i = 0; i < len; i++) {
        const uint8_t *g = glyph_for(s[i]);
        for (int col = 0; col < 5; col++) {
            for (int row = 0; row < 7; row++) {
                if (!(g[col] >> row & 1))
                    continue;
                for (int sy = 0; sy < scale; sy++) {
                    for (int sx = 0; sx < scale; sx++) {
                        int px = x0 + i * char_w + col * scale + sx;
                        int py = y + row * scale + sy;
                        if (px >= 0 && px < disp_w && py >= 0 && py < disp_h)
                            framebuf[py * disp_w + px] = color;
                    }
                }
            }
        }
    }
}

/* Generic message screen: centered lines on black, night-vision red. Lines
 * short enough for the big font are drawn at 2x, longer ones at 1x. Used by
 * pifinder-watchdog for the update-failure screen; usable by any boot-time
 * service that needs to talk to the operator without the app running. */
static void draw_message(char *const lines[], int nlines) {
    memset(framebuf, 0, sizeof(uint16_t) * disp_w * disp_h);

    /* Pick a scale per line and total the height (7*scale + 5px gap each). */
    int scales[16];
    int total_h = 0;
    if (nlines > 16) nlines = 16;
    for (int i = 0; i < nlines; i++) {
        scales[i] = ((int)strlen(lines[i]) * 12 <= disp_w) ? 2 : 1;
        total_h += 7 * scales[i] + 5;
    }

    int y = (disp_h - total_h) / 2;
    if (y < 0) y = 0;
    for (int i = 0; i < nlines; i++) {
        draw_text_centered(y, lines[i], scales[i], COL_RED);
        y += 7 * scales[i] + 5;
    }
    oled_flush();
}

static int hw_init(void) {
    spi_fd = open(SPI_DEVICE, O_RDWR);
    if (spi_fd < 0) {
        perror("open spi");
        return -1;
    }

    uint8_t mode = SPI_MODE_0;
    uint8_t bits = 8;
    uint32_t speed = SPI_SPEED;
    ioctl(spi_fd, SPI_IOC_WR_MODE, &mode);
    ioctl(spi_fd, SPI_IOC_WR_BITS_PER_WORD, &bits);
    ioctl(spi_fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed);

    gpio_fd = open("/dev/gpiochip0", O_RDWR);
    if (gpio_fd < 0) {
        perror("open gpiochip0");
        return -1;
    }

    if (gpio_request_line(gpio_fd, GPIO_DC, &dc_req) < 0)
        return -1;
    if (gpio_request_line(gpio_fd, GPIO_RST, &rst_req) < 0)
        return -1;

    if (panel == PANEL_SSD1333)
        ssd1333_init();
    else
        ssd1351_init();
    return 0;
}

static void hw_cleanup(void) {
    if (dc_req.fd > 0) close(dc_req.fd);
    if (rst_req.fd > 0) close(rst_req.fd);
    if (gpio_fd >= 0) close(gpio_fd);
    if (spi_fd >= 0) close(spi_fd);
}

static void show_static_image(void) {
    draw_welcome();
    oled_flush();
}

int main(int argc, char *argv[]) {
    int static_mode = 0;
    int progress_mode = 0;
    const char *progress_path = PROGRESS_FILE_DEFAULT;
    char **message_lines = NULL;
    int message_nlines = 0;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--static") == 0) {
            static_mode = 1;
        } else if (strcmp(argv[i], "--progress") == 0) {
            progress_mode = 1;
            /* Optional next arg overrides the progress file path */
            if (i + 1 < argc && argv[i + 1][0] != '-') {
                progress_path = argv[++i];
            }
        } else if (strcmp(argv[i], "--message") == 0) {
            /* All remaining args are message lines */
            message_lines = &argv[i + 1];
            message_nlines = argc - i - 1;
            break;
        }
    }

    signal(SIGTERM, signal_handler);
    signal(SIGINT, signal_handler);

    detect_panel();

    if (hw_init() < 0) {
        fprintf(stderr, "Hardware init failed\n");
        hw_cleanup();
        return 1;
    }

    /* Turn on display */
    oled_cmd(0xAF);

    if (static_mode) {
        /* Static mode: show image once and exit */
        show_static_image();
        hw_cleanup();
        return 0;
    }

    if (message_nlines > 0) {
        /* Message mode: render the lines once and exit, leaving them shown */
        draw_message(message_lines, message_nlines);
        hw_cleanup();
        return 0;
    }

    if (progress_mode) {
        /* Progress mode: render a real bar from the progress file until 100%
         * or until signalled. Only flush when the value changes. */
        int last = -1;
        while (running) {
            int pct = read_progress(progress_path);
            if (pct < 0) pct = 0;
            if (pct != last) {
                draw_progress(pct);
                last = pct;
            }
            if (pct >= 100) break;
            msleep(100);
        }
        hw_cleanup();
        return 0;
    }

    /* Animation mode: Knight Rider scanner */
    int pos = 0;
    int dir = 1;
    int scanner_width = 20;

    while (running) {
        draw_scanner(pos, scanner_width);

        pos += dir * 4;  /* Speed */
        if (pos >= disp_w - scanner_width/2) {
            pos = disp_w - scanner_width/2;
            dir = -1;
        } else if (pos <= scanner_width/2) {
            pos = scanner_width/2;
            dir = 1;
        }

        msleep(30);  /* ~33 FPS */
    }

    hw_cleanup();
    return 0;
}
