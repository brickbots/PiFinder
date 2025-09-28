
class MountControlBase:
    def __init__(self):
        pass

    def init(self):
        raise NotImplementedError("This method should be overridden by subclasses.")

    def disconnect(self):
        raise NotImplementedError("This method should be overridden by subclasses.")

    def move_to_position(self, position):
        raise NotImplementedError("This method should be overridden by subclasses.")

    def get_current_position(self):
        raise NotImplementedError("This method should be overridden by subclasses.")