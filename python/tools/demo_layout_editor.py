"""
Edit the layout of the demo display (``--display pg_demo``).

Shows the photo with a circle on each button and a frame on the screen area.
Drag a circle to move a button. Drag the top-left handle of the frame to move
the screen area, and the bottom-right handle to change its size. Each release
of the mouse saves ``images/demo_display/layout.json``. Close the window to
stop.

    cd python && uv run python tools/demo_layout_editor.py
"""

import pygame

from PiFinder.demo_display import DemoLayout

GRAB_RADIUS = 14
BUTTON_COLOR = (0, 255, 0)
SCREEN_COLOR = (0, 200, 255)
ACTIVE_COLOR = (255, 255, 0)


def main() -> None:
    layout = DemoLayout.load()
    pygame.init()
    background = pygame.image.load(str(layout.background))
    window = pygame.display.set_mode(background.get_size())
    pygame.display.set_caption("Demo layout: drag to edit, close to stop")
    font = pygame.font.SysFont("monospace", 14, bold=True)
    clock = pygame.time.Clock()

    # One of: a button name, "SCREEN_MOVE", "SCREEN_SIZE", or None.
    dragging = None

    running = True
    while running:
        x, y, w, h = layout.screen
        handles = {"SCREEN_MOVE": (x, y), "SCREEN_SIZE": (x + w, y + h)}

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                dragging = next(
                    (
                        name
                        for name, (hx, hy) in handles.items()
                        if (mx - hx) ** 2 + (my - hy) ** 2 <= GRAB_RADIUS**2
                    ),
                    None,
                ) or layout.button_at(event.pos)
            elif event.type == pygame.MOUSEBUTTONUP:
                if dragging is not None:
                    layout.save()
                dragging = None
            elif event.type == pygame.MOUSEMOTION and dragging is not None:
                mx, my = event.pos
                if dragging == "SCREEN_MOVE":
                    layout.screen = (mx, my, w, h)
                elif dragging == "SCREEN_SIZE":
                    layout.screen = (x, y, max(16, mx - x), max(16, my - y))
                else:
                    layout.buttons[dragging] = (mx, my)

        window.blit(background, (0, 0))
        x, y, w, h = layout.screen
        pygame.draw.rect(window, SCREEN_COLOR, (x, y, w, h), 2)
        label = font.render(f"SCREEN {w}x{h}", True, SCREEN_COLOR)
        window.blit(label, (x, y - 18))
        for name, pos in {"SCREEN_MOVE": (x, y), "SCREEN_SIZE": (x + w, y + h)}.items():
            color = ACTIVE_COLOR if name == dragging else SCREEN_COLOR
            pygame.draw.circle(window, color, pos, 6)

        for name, (bx, by) in layout.buttons.items():
            color = ACTIVE_COLOR if name == dragging else BUTTON_COLOR
            pygame.draw.circle(window, color, (bx, by), layout.button_radius, 2)
            window.blit(
                font.render(name, True, color), (bx + layout.button_radius + 4, by - 8)
            )

        pygame.display.flip()
        clock.tick(60)

    layout.save()
    pygame.quit()


if __name__ == "__main__":
    main()
