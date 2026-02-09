/*
 * boot-splash - Early boot splash for PiFinder
 *
 * Displays welcome image with Knight Rider animation until stopped.
 * Designed for NixOS early boot (before Python starts).
 *
 * Hardware: SPI0.0, DC=GPIO24, RST=GPIO25, 128x128 SSD1351 OLED
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

#define WIDTH 128
#define HEIGHT 128
#define SPI_DEVICE "/dev/spidev0.0"
#define SPI_SPEED 40000000
#define GPIO_DC 24
#define GPIO_RST 25

/* BGR565 colors */
#define COL_BLACK   0x0000
#define COL_RED     0x001F

/* Include generated image data */
#include "welcome_image.h"

static int spi_fd = -1;
static int gpio_fd = -1;
static struct gpio_v2_line_request dc_req;
static struct gpio_v2_line_request rst_req;
static uint16_t framebuf[WIDTH * HEIGHT];
static volatile int running = 1;

static void signal_handler(int sig) {
    (void)sig;
    running = 0;
}

static void msleep(int ms) {
    struct timespec ts = { .tv_sec = ms / 1000, .tv_nsec = (ms % 1000) * 1000000L };
    nanosleep(&ts, NULL);
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

static void ssd1351_cmd(uint8_t cmd) {
    gpio_set(&dc_req, 0);
    spi_write(&cmd, 1);
}

static void ssd1351_data(const uint8_t *data, size_t len) {
    gpio_set(&dc_req, 1);
    spi_write(data, len);
}

static void ssd1351_init(void) {
    uint8_t d;

    /* Hardware reset */
    gpio_set(&rst_req, 1);
    msleep(10);
    gpio_set(&rst_req, 0);
    msleep(10);
    gpio_set(&rst_req, 1);
    msleep(10);

    ssd1351_cmd(0xFD); d = 0x12; ssd1351_data(&d, 1); /* Unlock */
    ssd1351_cmd(0xFD); d = 0xB1; ssd1351_data(&d, 1); /* Unlock commands */
    ssd1351_cmd(0xAE); /* Display off */
    ssd1351_cmd(0xB3); d = 0xF1; ssd1351_data(&d, 1); /* Clock divider */
    ssd1351_cmd(0xCA); d = 0x7F; ssd1351_data(&d, 1); /* Mux ratio */

    uint8_t col[2] = {0x00, 0x7F};
    ssd1351_cmd(0x15); ssd1351_data(col, 2); /* Column address */
    uint8_t row[2] = {0x00, 0x7F};
    ssd1351_cmd(0x75); ssd1351_data(row, 2); /* Row address */

    ssd1351_cmd(0xA0); d = 0x74; ssd1351_data(&d, 1); /* BGR, 65k color */
    ssd1351_cmd(0xA1); d = 0x00; ssd1351_data(&d, 1); /* Start line */
    ssd1351_cmd(0xA2); d = 0x00; ssd1351_data(&d, 1); /* Display offset */
    ssd1351_cmd(0xB5); d = 0x00; ssd1351_data(&d, 1); /* GPIO */
    ssd1351_cmd(0xAB); d = 0x01; ssd1351_data(&d, 1); /* Function select */
    ssd1351_cmd(0xB1); d = 0x32; ssd1351_data(&d, 1); /* Precharge */

    uint8_t vsl[3] = {0xA0, 0xB5, 0x55};
    ssd1351_cmd(0xB4); ssd1351_data(vsl, 3); /* VSL */

    ssd1351_cmd(0xBE); d = 0x05; ssd1351_data(&d, 1); /* VCOMH */
    ssd1351_cmd(0xC7); d = 0x0F; ssd1351_data(&d, 1); /* Master contrast */
    ssd1351_cmd(0xB6); d = 0x01; ssd1351_data(&d, 1); /* Precharge2 */
    ssd1351_cmd(0xA6); /* Normal display */

    uint8_t contrast[3] = {0xFF, 0xFF, 0xFF};
    ssd1351_cmd(0xC1); ssd1351_data(contrast, 3); /* Contrast */
}

static void ssd1351_flush(void) {
    uint8_t col[2] = {0x00, 0x7F};
    ssd1351_cmd(0x15); ssd1351_data(col, 2);
    uint8_t row[2] = {0x00, 0x7F};
    ssd1351_cmd(0x75); ssd1351_data(row, 2);
    ssd1351_cmd(0x5C); /* Write RAM */

    uint8_t buf[WIDTH * HEIGHT * 2];
    for (int i = 0; i < WIDTH * HEIGHT; i++) {
        buf[i * 2] = framebuf[i] >> 8;
        buf[i * 2 + 1] = framebuf[i] & 0xFF;
    }
    ssd1351_data(buf, sizeof(buf));
}

static void draw_scanner(int pos, int scanner_width) {
    /* Copy welcome image to framebuffer */
    memcpy(framebuf, welcome_image, sizeof(framebuf));

    /* Draw Knight Rider scanner at bottom (last 4 rows) */
    int y_start = HEIGHT - 4;
    int center = pos;

    for (int x = 0; x < WIDTH; x++) {
        int dist = abs(x - center);
        uint16_t color = COL_BLACK;

        if (dist < scanner_width) {
            /* Gradient: brighter at center, RED color in BGR565 */
            int intensity = 31 - (dist * 31 / scanner_width);
            if (intensity < 8) intensity = 8;  /* Minimum brightness */
            /* BGR565: BBBBBGGGGGGRRRRR - red is lowest 5 bits (0x001F = max red) */
            color = (uint16_t)intensity & 0x1F;
        }

        for (int y = y_start; y < HEIGHT; y++) {
            framebuf[y * WIDTH + x] = color;
        }
    }

    ssd1351_flush();
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

    ssd1351_init();
    return 0;
}

static void hw_cleanup(void) {
    if (dc_req.fd > 0) close(dc_req.fd);
    if (rst_req.fd > 0) close(rst_req.fd);
    if (gpio_fd >= 0) close(gpio_fd);
    if (spi_fd >= 0) close(spi_fd);
}

int main(int argc, char *argv[]) {
    (void)argc;
    (void)argv;

    signal(SIGTERM, signal_handler);
    signal(SIGINT, signal_handler);

    if (hw_init() < 0) {
        fprintf(stderr, "Hardware init failed\n");
        hw_cleanup();
        return 1;
    }

    /* Turn on display */
    ssd1351_cmd(0xAF);

    int pos = 0;
    int dir = 1;
    int scanner_width = 20;

    while (running) {
        draw_scanner(pos, scanner_width);

        pos += dir * 4;  /* Speed */
        if (pos >= WIDTH - scanner_width/2) {
            pos = WIDTH - scanner_width/2;
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
