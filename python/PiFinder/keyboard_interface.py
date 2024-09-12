from time import sleep
import logging

from PiFinder.multiproclogging import MultiprocLogging

logger = logging.getLogger("Keyboard.Interface")


class KeyboardInterface:
    NA = 10
    PLUS = 11
    MINUS = 12
    SQUARE = 13
    LEFT = 20
    UP = 21
    DOWN = 22
    RIGHT = 24
    ALT_PLUS = 101
    ALT_MINUS = 102
    ALT_LEFT = 103
    ALT_UP = 104
    ALT_DOWN = 105
    ALT_RIGHT = 106
    ALT_0 = 110
    LNG_LEFT = 200
    LNG_UP = 201
    LNG_DOWN = 202
    LNG_RIGHT = 203
    LNG_SQUARE = 204

    def __init__(self, q=None):
        self.q = q

    def run_keyboard(self):
        pass

    @staticmethod
    def run_script(script_name, q, log_queue):
        """
        Runs a keyscript for automation/testing
        """
        MultiprocLogging.configurer(log_queue)
        logger.info("Running Script: " + script_name)
        with open(script_name) as script_file:
            script = script_file.readlines()
            length = len(script)
            for idx, script_line in enumerate(script):
                sleep(0.1)
                script_line = script_line.strip()
                logger.debug("(%i/%i)\t%s", idx, length, script_line)
                script_tokens = script_line.split(" ")
                if script_tokens[0].startswith("#"):
                    # comment
                    pass
                elif script_tokens[0] == "":
                    # blank line
                    pass
                elif script_tokens[0] == "wait":
                    sleep(int(script_tokens[1]))
                else:
                    # must be keycode
                    if script_tokens[0].isnumeric():
                        q.put(int(script_tokens[0]))
                    else:
                        try:
                            q.put(eval("KeyboardInterface." + script_tokens[0]))
                        except NameError:
                            q.put(KeyboardInterface.NA)
                sleep(0.1)
        logging.info("Script Complete")
        import os

        os._exit(1)
