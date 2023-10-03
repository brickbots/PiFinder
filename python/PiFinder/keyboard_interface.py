from time import sleep
import logging


class KeyboardInterface:
    NA = 10
    UP = 11
    DN = 12
    ENT = 13
    A = 20
    B = 21
    C = 22
    D = 24
    ALT_UP = 101
    ALT_DN = 102
    ALT_A = 103
    ALT_B = 104
    ALT_C = 105
    ALT_D = 106
    ALT_0 = 110
    LNG_A = 200
    LNG_B = 201
    LNG_C = 202
    LNG_D = 203
    LNG_ENT = 204

    def __init__(self, q=None):
        self.q = q

    def run_keyboard(self):
        pass

    @staticmethod
    def run_script(script_name, q):
        """
        Runs a keyscript for automation/testing
        """
        logging.info("Running Script: " + script_name)
        with open(script_name) as script_file:
            script = script_file.readlines()
            length = len(script)
            for idx, script_line in enumerate(script):
                sleep(0.5)
                script_line = script_line.strip()
                logging.debug(f"({idx}/{length})\t{script_line}")
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
                        except:
                            q.put(KeyboardInterface.NA)
                sleep(0.1)
        logging.info("Script Complete")
        import os

        os._exit(1)
