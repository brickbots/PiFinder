import json
from typing import Any

from PIL import Image
import numpy as np
from numpy.typing import ArrayLike

import astroalign

class Stacker:
    def __init__(self, image_size: tuple[int, int] = (515, 515)):
        self.stack_solution: dict[Any, Any] = {}
        self.stack_image: Image.Image = Image.new("RGB", image_size)
        self.stack_array: ArrayLike = np.array(self.stack_image)
        self.stack_count: int = 0

    def match_centroids(self, solution: dict[str, Any]) -> (list[tuple[float, float]], list[tuple[float, float]]):
        """
        Returns a list of matched pixel positions between stars
        in the stack solution and the provided solution

        Uses Ra/Dec/Mag to find matching stars/centroids
        """
        source_centroids: list[tuple[float,float]] = []
        target_centroids: list[tuple[float,float]] = []
        for ti, tstar in enumerate(self.stack_solution["matched_stars"]):
           for si, sstar in enumerate(solution["matched_stars"]):
               if sstar == tstar:
                   source_centroids.append(solution["matched_centroids"][si])
                   target_centroids.append(self.stack_solution["matched_centroids"][ti])
                   break

        return source_centroids, target_centroids

    def add_image(
        self,
        image_to_add: Image.Image,
        solution: dict[Any, Any],
    ) -> bool:
        """
        Add an image to the stack after aligning it
        """

        self.stack_count += 1

        if self.stack_count == 1:
            # special case, first image to be added
            self.stack_array = np.array(image_to_add)
            self.stack_image = image_to_add
            self.stack_solution = solution
            return True

        _tmp_array: ArrayLike = np.array(self.align_image(image_to_add, solution))

        # Scale the current stack to make room for the next contribution
        stack_scale_amount: float = (self.stack_count - 1) / self.stack_count
        self.stack_array = np.multiply(self.stack_array, stack_scale_amount)

        # Scale the new image to prep for addition
        _tmp_array = np.divide(_tmp_array, self.stack_count)

        # Add the array
        self.stack_array = self.stack_array + _tmp_array

        self.stack_image = Image.fromarray(self.stack_array.astype(np.int8), "RGB")

        return True

    def align_image(
        self,
        image_to_align: Image.Image,
        solution: dict[Any, Any],
    ) -> Image.Image:
        """
        Align an image to the current stack
        """

        source_centroids, target_centroids = self.match_centroids(solution)
        tform = astroalign.estimate_transform(
            'affine',
            np.array(source_centroids),
            np.array(target_centroids),
        )

        tform = list(tform.params[0]) + list(tform.params[1])
        print(tform)
        aligned_image = image_to_align.transform((512,512), Image.AFFINE, tform, Image.BICUBIC)

        return aligned_image

    def get_stack_image(self) -> Image.Image:
        """
        Returns the current stack as an RGB pil image
        """
        return self.stack_image

    def save_stack(self, filename: str) -> bool:
        self.get_stack_image().save(filename)
        return True


def test_stack(start_image: int, end_image: int) -> None:
    stack = Stacker()
    for i in range(start_image, end_image + 1):
        print(i)
        _tmp_image: Image.Image = Image.open(f"/Users/rich/stack/stack/{i:04}.png")
        _tmp_solution: dict[Any, Any] = json.load(
            open(f"/Users/rich/stack/stack/{i:04}.json", "r")
        )
        stack.add_image(_tmp_image, _tmp_solution)
        stack.save_stack(f"/Users/rich/stack/stage_{i:04}.png")

    stack.save_stack("/Users/rich/stack/test.png")
