from time import sleep


class KeyboardInterface:
    def run_keyboard(self, q, script_path=None):
        pass

    def run_script(self, q, script_path):
        """
        Runs a keyscript for automation/testing
        """
        print("Running Script: " + script_path)
        with open(script_path + ".pfs", "r") as script_file:
            for script_line in script_file:
                sleep(0.5)
                script_line = script_line.strip()
                print(f"\t{script_line}")
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
                        q.put(eval(script_tokens[0]))

    def set_brightness(self, level, cfg):
        pass
