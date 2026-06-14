/*
 * migration_progress - OLED progress display for PiFinder initramfs
 *
 * Drives supported SPI OLED displays to show migration progress.
 * Designed to be statically compiled and included in the initramfs.
 *
 * Usage: migration_progress <percent> <stage_num> <stage_total> <message>
 *   percent: 0-100
 *   message: status text (max ~20 chars fits on screen)
 *
 * Examples:
 *   migration_progress 0 1 22 "Starting..."
 *   migration_progress 45 10 22 "Moving data"
 *   migration_progress 100 22 22 "Complete!"
 *
 * Hardware: SPI0.0, DC=GPIO24, RST=GPIO25, BGR565
 */

#include <fcntl.h>
#include <linux/gpio.h>
#include <linux/spi/spidev.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define MAX_WIDTH 176
#define MAX_HEIGHT 176
#define SPI_DEVICE "/dev/spidev0.0"
#define SPI_SPEED 40000000
#define GPIO_DC 24
#define GPIO_RST 25

/* BGR565 colors */
#define COL_BLACK   0x0000
#define COL_WHITE   0xFFFF
#define COL_RED     0x001F  /* BGR565: blue=0, green=0, red=31 */
#define COL_GREEN   0x07E0
#define COL_DKGRAY  0x4208
#define COL_DKRED   0x0010

static int spi_fd = -1;
static int gpio_fd = -1;
static struct gpio_v2_line_request dc_req;
static struct gpio_v2_line_request rst_req;
static uint16_t framebuf[MAX_WIDTH * MAX_HEIGHT];

enum oled_controller {
    CTRL_SSD1351,
    CTRL_SSD1333,
};

static enum oled_controller controller = CTRL_SSD1351;
static int display_width = 128;
static int display_height = 128;

/* 5x7 bitmap font - ASCII 32-126 */
static const uint8_t font5x7[][5] = {
    {0x00,0x00,0x00,0x00,0x00}, /* space */
    {0x00,0x00,0x5F,0x00,0x00}, /* ! */
    {0x00,0x07,0x00,0x07,0x00}, /* " */
    {0x14,0x7F,0x14,0x7F,0x14}, /* # */
    {0x24,0x2A,0x7F,0x2A,0x12}, /* $ */
    {0x23,0x13,0x08,0x64,0x62}, /* % */
    {0x36,0x49,0x55,0x22,0x50}, /* & */
    {0x00,0x05,0x03,0x00,0x00}, /* ' */
    {0x00,0x1C,0x22,0x41,0x00}, /* ( */
    {0x00,0x41,0x22,0x1C,0x00}, /* ) */
    {0x08,0x2A,0x1C,0x2A,0x08}, /* * */
    {0x08,0x08,0x3E,0x08,0x08}, /* + */
    {0x00,0x50,0x30,0x00,0x00}, /* , */
    {0x08,0x08,0x08,0x08,0x08}, /* - */
    {0x00,0x60,0x60,0x00,0x00}, /* . */
    {0x20,0x10,0x08,0x04,0x02}, /* / */
    {0x3E,0x51,0x49,0x45,0x3E}, /* 0 */
    {0x00,0x42,0x7F,0x40,0x00}, /* 1 */
    {0x42,0x61,0x51,0x49,0x46}, /* 2 */
    {0x21,0x41,0x45,0x4B,0x31}, /* 3 */
    {0x18,0x14,0x12,0x7F,0x10}, /* 4 */
    {0x27,0x45,0x45,0x45,0x39}, /* 5 */
    {0x3C,0x4A,0x49,0x49,0x30}, /* 6 */
    {0x01,0x71,0x09,0x05,0x03}, /* 7 */
    {0x36,0x49,0x49,0x49,0x36}, /* 8 */
    {0x06,0x49,0x49,0x29,0x1E}, /* 9 */
    {0x00,0x36,0x36,0x00,0x00}, /* : */
    {0x00,0x56,0x36,0x00,0x00}, /* ; */
    {0x00,0x08,0x14,0x22,0x41}, /* < */
    {0x14,0x14,0x14,0x14,0x14}, /* = */
    {0x41,0x22,0x14,0x08,0x00}, /* > */
    {0x02,0x01,0x51,0x09,0x06}, /* ? */
    {0x32,0x49,0x79,0x41,0x3E}, /* @ */
    {0x7E,0x11,0x11,0x11,0x7E}, /* A */
    {0x7F,0x49,0x49,0x49,0x36}, /* B */
    {0x3E,0x41,0x41,0x41,0x22}, /* C */
    {0x7F,0x41,0x41,0x22,0x1C}, /* D */
    {0x7F,0x49,0x49,0x49,0x41}, /* E */
    {0x7F,0x09,0x09,0x01,0x01}, /* F */
    {0x3E,0x41,0x41,0x51,0x32}, /* G */
    {0x7F,0x08,0x08,0x08,0x7F}, /* H */
    {0x00,0x41,0x7F,0x41,0x00}, /* I */
    {0x20,0x40,0x41,0x3F,0x01}, /* J */
    {0x7F,0x08,0x14,0x22,0x41}, /* K */
    {0x7F,0x40,0x40,0x40,0x40}, /* L */
    {0x7F,0x02,0x04,0x02,0x7F}, /* M */
    {0x7F,0x04,0x08,0x10,0x7F}, /* N */
    {0x3E,0x41,0x41,0x41,0x3E}, /* O */
    {0x7F,0x09,0x09,0x09,0x06}, /* P */
    {0x3E,0x41,0x51,0x21,0x5E}, /* Q */
    {0x7F,0x09,0x19,0x29,0x46}, /* R */
    {0x46,0x49,0x49,0x49,0x31}, /* S */
    {0x01,0x01,0x7F,0x01,0x01}, /* T */
    {0x3F,0x40,0x40,0x40,0x3F}, /* U */
    {0x1F,0x20,0x40,0x20,0x1F}, /* V */
    {0x7F,0x20,0x18,0x20,0x7F}, /* W */
    {0x63,0x14,0x08,0x14,0x63}, /* X */
    {0x03,0x04,0x78,0x04,0x03}, /* Y */
    {0x61,0x51,0x49,0x45,0x43}, /* Z */
    {0x00,0x00,0x7F,0x41,0x41}, /* [ */
    {0x02,0x04,0x08,0x10,0x20}, /* \ */
    {0x41,0x41,0x7F,0x00,0x00}, /* ] */
    {0x04,0x02,0x01,0x02,0x04}, /* ^ */
    {0x40,0x40,0x40,0x40,0x40}, /* _ */
    {0x00,0x01,0x02,0x04,0x00}, /* ` */
    {0x20,0x54,0x54,0x54,0x78}, /* a */
    {0x7F,0x48,0x44,0x44,0x38}, /* b */
    {0x38,0x44,0x44,0x44,0x20}, /* c */
    {0x38,0x44,0x44,0x48,0x7F}, /* d */
    {0x38,0x54,0x54,0x54,0x18}, /* e */
    {0x08,0x7E,0x09,0x01,0x02}, /* f */
    {0x08,0x14,0x54,0x54,0x3C}, /* g */
    {0x7F,0x08,0x04,0x04,0x78}, /* h */
    {0x00,0x44,0x7D,0x40,0x00}, /* i */
    {0x20,0x40,0x44,0x3D,0x00}, /* j */
    {0x00,0x7F,0x10,0x28,0x44}, /* k */
    {0x00,0x41,0x7F,0x40,0x00}, /* l */
    {0x7C,0x04,0x18,0x04,0x78}, /* m */
    {0x7C,0x08,0x04,0x04,0x78}, /* n */
    {0x38,0x44,0x44,0x44,0x38}, /* o */
    {0x7C,0x14,0x14,0x14,0x08}, /* p */
    {0x08,0x14,0x14,0x18,0x7C}, /* q */
    {0x7C,0x08,0x04,0x04,0x08}, /* r */
    {0x48,0x54,0x54,0x54,0x20}, /* s */
    {0x04,0x3F,0x44,0x40,0x20}, /* t */
    {0x3C,0x40,0x40,0x20,0x7C}, /* u */
    {0x1C,0x20,0x40,0x20,0x1C}, /* v */
    {0x3C,0x40,0x30,0x40,0x3C}, /* w */
    {0x44,0x28,0x10,0x28,0x44}, /* x */
    {0x0C,0x50,0x50,0x50,0x3C}, /* y */
    {0x44,0x64,0x54,0x4C,0x44}, /* z */
    {0x00,0x08,0x36,0x41,0x00}, /* { */
    {0x00,0x00,0x7F,0x00,0x00}, /* | */
    {0x00,0x41,0x36,0x08,0x00}, /* } */
    {0x08,0x08,0x2A,0x1C,0x08}, /* ~ */
};

static void msleep(int ms)
{
    struct timespec ts = { .tv_sec = ms / 1000, .tv_nsec = (ms % 1000) * 1000000L };
    nanosleep(&ts, NULL);
}

static int gpio_request_line(int chip_fd, int pin, struct gpio_v2_line_request *req)
{
    struct gpio_v2_line_request r = {0};
    r.offsets[0] = pin;
    r.num_lines = 1;
    r.config.flags = GPIO_V2_LINE_FLAG_OUTPUT;
    snprintf(r.consumer, sizeof(r.consumer), "migration");

    if (ioctl(chip_fd, GPIO_V2_GET_LINE_IOCTL, &r) < 0) {
        perror("GPIO_V2_GET_LINE_IOCTL");
        return -1;
    }
    *req = r;
    return 0;
}

static void gpio_set(struct gpio_v2_line_request *req, int value)
{
    struct gpio_v2_line_values vals = {0};
    vals.bits = value ? 1 : 0;
    vals.mask = 1;
    ioctl(req->fd, GPIO_V2_LINE_SET_VALUES_IOCTL, &vals);
}

static void spi_write(const uint8_t *data, size_t len)
{
    /* Chunk large transfers - SPI driver may limit to 4KB */
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

static void oled_cmd(uint8_t cmd)
{
    gpio_set(&dc_req, 0);
    spi_write(&cmd, 1);
}

static void oled_data(const uint8_t *data, size_t len)
{
    gpio_set(&dc_req, 1);
    spi_write(data, len);
}

static void oled_cmd_data(uint8_t cmd, uint8_t data)
{
    oled_cmd(cmd);
    oled_data(&data, 1);
}

static int skip_reset = 0;  /* set via --update flag in main */
static int display_on = 0;

static void detect_display(void)
{
    const char *display_class = getenv("MIGRATION_DISPLAY_CLASS");
    const char *display_resolution = getenv("MIGRATION_DISPLAY_RESOLUTION");

    controller = CTRL_SSD1351;
    display_width = 128;
    display_height = 128;

    if (display_class && strstr(display_class, "SSD1333")) {
        controller = CTRL_SSD1333;
        display_width = 176;
        display_height = 176;
        return;
    }

    if (display_resolution && strcmp(display_resolution, "176x176") == 0) {
        controller = CTRL_SSD1333;
        display_width = 176;
        display_height = 176;
    }
}

static void oled_reset(void)
{
    gpio_set(&rst_req, 1);
    msleep(10);
    gpio_set(&rst_req, 0);
    msleep(10);
    gpio_set(&rst_req, 1);
    msleep(10);
}

static void oled_common_init(int mux_ratio, uint8_t remap)
{
    if (skip_reset) {
        /* Just ensure display is on, skip full init */
        oled_cmd(0xAF);
        display_on = 1;
        return;
    }

    oled_reset();

    /* SSD13xx 65k-color OLED setup. */
    oled_cmd_data(0xFD, 0x12); /* Unlock */
    oled_cmd_data(0xFD, 0xB1); /* Unlock commands */

    oled_cmd(0xAE); /* Display off */
    oled_cmd_data(0xB3, 0xF1); /* Clock divider */
    oled_cmd_data(0xCA, (uint8_t)mux_ratio); /* Mux ratio */

    oled_cmd(0x15); /* Column address */
    uint8_t col[2] = {0x00, (uint8_t)(display_width - 1)};
    oled_data(col, 2);

    oled_cmd(0x75); /* Row address */
    uint8_t row[2] = {0x00, (uint8_t)(display_height - 1)};
    oled_data(row, 2);

    oled_cmd_data(0xA0, remap); /* Remap/color depth */
    oled_cmd_data(0xA1, 0x00); /* Start line */
    oled_cmd_data(0xA2, 0x00); /* Display offset */
    oled_cmd_data(0xB5, 0x00); /* GPIO */
    oled_cmd_data(0xAB, 0x01); /* Function select */
    oled_cmd_data(0xB1, 0x32); /* Precharge */

    oled_cmd(0xB4); /* VSL */
    uint8_t vsl[3] = {0xA0, 0xB5, 0x55};
    oled_data(vsl, 3);

    oled_cmd_data(0xBE, 0x05); /* VCOMH */
    oled_cmd_data(0xC7, 0x0F); /* Master contrast */
    oled_cmd_data(0xB6, 0x01); /* Precharge2 */
    oled_cmd(0xA6); /* Normal display */

    /* Display ON (0xAF) happens after first framebuffer flush. */
}

static void oled_init(void)
{
    if (controller == CTRL_SSD1333)
        oled_common_init(0xAF, 0x74);
    else
        oled_common_init(0x7F, 0x74);
}

static void oled_flush(void)
{
    /* Set contrast before first frame (matching luma) */
    if (!display_on) {
        oled_cmd(0xC1); /* Contrast */
        uint8_t contrast[3] = {0xFF, 0xFF, 0xFF};
        oled_data(contrast, 3);
    }

    oled_cmd(0x15);
    uint8_t col[2] = {0x00, (uint8_t)(display_width - 1)};
    oled_data(col, 2);

    oled_cmd(0x75);
    uint8_t row[2] = {0x00, (uint8_t)(display_height - 1)};
    oled_data(row, 2);

    oled_cmd(0x5C); /* Write RAM */

    /* Send framebuffer as big-endian 16-bit pixels */
    uint8_t buf[MAX_WIDTH * MAX_HEIGHT * 2];
    int pixels = display_width * display_height;
    for (int i = 0; i < pixels; i++) {
        buf[i * 2] = framebuf[i] >> 8;
        buf[i * 2 + 1] = framebuf[i] & 0xFF;
    }
    oled_data(buf, (size_t)pixels * 2);

    /* Turn display on after first frame */
    if (!display_on) {
        oled_cmd(0xAF); /* Display on */
        display_on = 1;
    }
}

static void fb_clear(uint16_t color)
{
    for (int i = 0; i < display_width * display_height; i++)
        framebuf[i] = color;
}

static void fb_pixel(int x, int y, uint16_t color)
{
    if (x >= 0 && x < display_width && y >= 0 && y < display_height)
        framebuf[y * display_width + x] = color;
}

static void fb_rect(int x, int y, int w, int h, uint16_t color)
{
    for (int j = y; j < y + h && j < display_height; j++)
        for (int i = x; i < x + w && i < display_width; i++)
            fb_pixel(i, j, color);
}

static void fb_char(int x, int y, char c, uint16_t color, int scale)
{
    if (c < 32 || c > 126)
        c = '?';
    const uint8_t *glyph = font5x7[c - 32];
    for (int col = 0; col < 5; col++) {
        uint8_t bits = glyph[col];
        for (int row = 0; row < 7; row++) {
            if (bits & (1 << row)) {
                for (int sy = 0; sy < scale; sy++)
                    for (int sx = 0; sx < scale; sx++)
                        fb_pixel(x + col * scale + sx,
                                 y + row * scale + sy, color);
            }
        }
    }
}

static void fb_string(int x, int y, const char *s, uint16_t color, int scale)
{
    int cx = x;
    while (*s) {
        fb_char(cx, y, *s, color, scale);
        cx += 6 * scale; /* 5px char + 1px gap */
        s++;
    }
}

/* Center a string horizontally */
static void fb_string_centered(int y, const char *s, uint16_t color, int scale)
{
    int len = strlen(s);
    int px_width = len * 6 * scale - scale; /* subtract trailing gap */
    int x = (display_width - px_width) / 2;
    if (x < 0) x = 0;
    fb_string(x, y, s, color, scale);
}

static void draw_progress(int percent, const char *stage, int stage_num, int stage_total)
{
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;

    fb_clear(COL_BLACK);

    int scale = display_width >= 160 ? 2 : 1;
    int margin = display_width >= 160 ? 14 : 10;
    int banner_h = display_width >= 160 ? 18 : 12;
    int title_y = display_width >= 160 ? 28 : 18;
    int subtitle_y = display_width >= 160 ? 55 : 38;
    int stage_y = display_width >= 160 ? 76 : 52;
    int bar_y = display_width >= 160 ? 94 : 65;
    int pct_y = display_width >= 160 ? 116 : 82;
    int stage_name_y = display_width >= 160 ? 145 : 105;
    int wait_y = display_height - (8 * scale);

    /* Warning banner at top */
    fb_rect(0, 0, display_width, banner_h, COL_DKRED);
    fb_string_centered(3, "DO NOT POWER OFF", COL_RED, scale);

    /* Title */
    fb_string_centered(title_y, "NixOS", COL_RED, 2);
    fb_string_centered(subtitle_y, "Migration", COL_RED, scale);

    /* Stage indicator (e.g., "3/7") */
    if (stage_total > 0) {
        char stage_str[32];
        snprintf(stage_str, sizeof(stage_str), "Stage %d/%d", stage_num, stage_total);
        fb_string_centered(stage_y, stage_str, COL_DKGRAY, scale);
    }

    /* Progress bar */
    int bar_x = margin;
    int bar_w = display_width - (margin * 2);
    int bar_h = display_width >= 160 ? 16 : 12;

    /* Border */
    fb_rect(bar_x, bar_y, bar_w, 1, COL_DKGRAY);
    fb_rect(bar_x, bar_y + bar_h - 1, bar_w, 1, COL_DKGRAY);
    fb_rect(bar_x, bar_y, 1, bar_h, COL_DKGRAY);
    fb_rect(bar_x + bar_w - 1, bar_y, 1, bar_h, COL_DKGRAY);

    /* Fill */
    int fill_w = (bar_w - 4) * percent / 100;
    if (fill_w > 0)
        fb_rect(bar_x + 2, bar_y + 2, fill_w, bar_h - 4, COL_RED);

    /* Dark red background for unfilled */
    int unfill_x = bar_x + 2 + fill_w;
    int unfill_w = (bar_w - 4) - fill_w;
    if (unfill_w > 0)
        fb_rect(unfill_x, bar_y + 2, unfill_w, bar_h - 4, COL_DKRED);

    /* Percentage */
    char pct_str[8];
    snprintf(pct_str, sizeof(pct_str), "%d%%", percent);
    fb_string_centered(pct_y, pct_str, COL_RED, 2);

    /* Current stage name */
    if (stage && *stage)
        fb_string_centered(stage_name_y, stage, COL_RED, scale);

    /* Bottom warning */
    fb_string_centered(wait_y, "Please wait...", COL_DKGRAY, scale);

    oled_flush();
}

static int hw_init(void)
{
    /* Open SPI */
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

    /* Open GPIO chip */
    gpio_fd = open("/dev/gpiochip0", O_RDWR);
    if (gpio_fd < 0) {
        perror("open gpiochip0");
        return -1;
    }

    if (gpio_request_line(gpio_fd, GPIO_DC, &dc_req) < 0)
        return -1;
    if (gpio_request_line(gpio_fd, GPIO_RST, &rst_req) < 0)
        return -1;

    detect_display();
    oled_init();
    return 0;
}

static void hw_cleanup(void)
{
    if (dc_req.fd > 0) close(dc_req.fd);
    if (rst_req.fd > 0) close(rst_req.fd);
    if (gpio_fd >= 0) close(gpio_fd);
    if (spi_fd >= 0) close(spi_fd);
}

int main(int argc, char *argv[])
{
    int arg_offset = 0;

    if (argc >= 2 && strcmp(argv[1], "--update") == 0) {
        skip_reset = 1;
        arg_offset = 1;
    }

    if (argc - arg_offset < 5) {
        fprintf(stderr, "Usage: %s [--update] <percent> <stage_num> <stage_total> <stage_name>\n", argv[0]);
        fprintf(stderr, "  --update     Skip reset, just update display\n");
        fprintf(stderr, "  percent      0-100\n");
        fprintf(stderr, "  stage_num    Current stage number (1-based)\n");
        fprintf(stderr, "  stage_total  Total number of stages\n");
        fprintf(stderr, "  stage_name   Description of current stage\n");
        fprintf(stderr, "\nExample: %s 50 3 7 'Extracting system'\n", argv[0]);
        return 1;
    }

    int percent = atoi(argv[1 + arg_offset]);
    int stage_num = atoi(argv[2 + arg_offset]);
    int stage_total = atoi(argv[3 + arg_offset]);
    const char *stage_name = argv[4 + arg_offset];

    if (hw_init() < 0) {
        fprintf(stderr, "Hardware init failed\n");
        hw_cleanup();
        return 1;
    }

    draw_progress(percent, stage_name, stage_num, stage_total);
    hw_cleanup();
    return 0;
}
