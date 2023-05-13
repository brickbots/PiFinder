# Copyright (c) 2022 Steven Karrmann
# SPDX-License-Identifier: MIT

# Horizon Board Producer Plugin Usage:
# 1. Copy this Python file (or create a symbolic link) in the KiCad plugins directory
#     * See: https://dev-docs.kicad.org/en/python/pcbnew/#_typical_plugin_structure
# 2. Open KiCad Pcbnew, and open the main board .kicad_pcb file
# 3. In Pcbnew, click "Tools > External Plugins > Horizon Board Producer"
# 4. If successful, 3 gerber zip files are created in the gerbers folder: main board, top plate, and bottom plate

import pcbnew, wx, os, shutil, re


class PiFinderBoardProducer(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "PiFinder Board Producer Rev2.3 (KiCad 6)"
        self.category = "Gerbers, plates, generator"
        self.description = "Generates top plate and bottom plate PCBs, and then creates gerber files for the main, top plate, and bottom plate PCBs"

    def Run(self):
        PiFinderBoardProducer.produce()

    @staticmethod
    def __create_gerbers(board, path):
        """
        Creates Gerber files for a KiCad board and outputs them to the specified path.

        Args:
            board (pcbnew.BOARD): The board for which to generate Gerber files.
            path (str): File system path where Gerber files will be created.
        """
        plot_controller = pcbnew.PLOT_CONTROLLER(board)
        plot_options = plot_controller.GetPlotOptions()

        # Set General Options:
        plot_options.SetOutputDirectory(path)

        plot_options.SetPlotFrameRef(False)  # "plot border and title block"
        plot_options.SetPlotValue(True)
        plot_options.SetPlotReference(True)
        plot_options.SetPlotInvisibleText(False)
        plot_options.SetExcludeEdgeLayer(True)
        plot_options.SetSketchPadsOnFabLayers(False)
        plot_options.SetPlotViaOnMaskLayer(False)  # "do not tent vias"

        plot_options.SetDrillMarksType(pcbnew.PCB_PLOT_PARAMS.NO_DRILL_SHAPE)
        plot_options.SetScale(1.0)
        plot_options.SetPlotMode(1)  # Filled
        plot_options.SetUseAuxOrigin(False)
        plot_options.SetMirror(False)
        plot_options.SetNegative(False)
        # Note: "check zone fills before plotting" does not seem to be available in API

        plot_options.SetUseGerberProtelExtensions(True)
        plot_options.SetCreateGerberJobFile(False)
        plot_options.SetSubtractMaskFromSilk(True)
        plot_options.SetGerberPrecision(6)  # "coordinate format: 4.6, unit mm"
        plot_options.SetUseGerberX2format(False)
        plot_options.SetIncludeGerberNetlistInfo(False)

        layers = [
            ("F.Cu", pcbnew.F_Cu, "Front Copper"),
            ("B.Cu", pcbnew.B_Cu, "Back Copper"),
            ("F.SilkS", pcbnew.F_SilkS, "Front SilkScreen"),
            ("B.SilkS", pcbnew.B_SilkS, "Back SilkScreen"),
            ("F.Mask", pcbnew.F_Mask, "Front Mask"),
            ("B.Mask", pcbnew.B_Mask, "Back Mask"),
            ("Edge.Cuts", pcbnew.Edge_Cuts, "Edges"),
        ]

        for layer in layers:
            plot_controller.SetLayer(layer[1])
            plot_controller.OpenPlotfile(layer[0], pcbnew.PLOT_FORMAT_GERBER, layer[2])
            plot_controller.PlotLayer()

        plot_controller.ClosePlot()

    @staticmethod
    def __create_drill_file(board, path):
        """
        Creates drill files for a KiCad board and outputs them to the specified path.

        Args:
            board (pcbnew.BOARD): The board for which to generate Gerber files.
            path (str): File system path where drill files will be created.
        """
        format = {
            "metric": True,
            "zero_format": pcbnew.GENDRILL_WRITER_BASE.DECIMAL_FORMAT,
            "left_digits": 3,
            "right_digits": 3,
        }

        options = {
            "mirror_y_axis": False,
            "minimal_header": False,
            "offset": pcbnew.wxPoint(0, 0),
            "pth_npth_single_file": False,
        }

        drill_writer = pcbnew.EXCELLON_WRITER(board)
        drill_writer.SetFormat(
            format["metric"],
            format["zero_format"],
            format["left_digits"],
            format["right_digits"],
        )
        drill_writer.SetOptions(
            options["mirror_y_axis"],
            options["minimal_header"],
            options["offset"],
            options["pth_npth_single_file"],
        )
        drill_writer.SetRouteModeForOvalHoles(
            False
        )  # JLCPCB requests (Oval Holes Drill Mode -> use alternate drill mode https://support.jlcpcb.com/article/149-how-to-generate-gerber-and-drill-files-in-kicad)
        drill_writer.CreateDrillandMapFilesSet(path, True, False)

    @staticmethod
    def __create_zip(zip_file_path, source_folder):
        """
        Creates a zip file containing all files in the source folder.

        Args:
            zip_file_path (str): The full path and file name for the new zip file.
            source_folder (str): The source folder containing the files to include in the zip.
        """
        return shutil.make_archive(zip_file_path, "zip", source_folder)

    @staticmethod
    def __create_plate_pcb_from_layer(board, layer_name):
        """
        Converts the provided board into a new cutout plate PCB, using layer data from the specified source board.
        All tracks and zones are removed from the plate, and only the footprint's cutouts are retained.
        These items within the bounds of the plate's cutout will be preserved:
          * Silkscreen directly on the board (but not in footprints)
          * LOGO footprints (silkscreen images)
          * H footprints (mounting holes)
        For all other footprints within the bounds of the plate's cutout:
          * SMD pads on the target layer are converted to non-plated through-hole pads.
          * Graphic lines on the target layer are converted to edge cuts.
          * All other pads and graphics are deleted.

        Args:
            board (pcbnew.BOARD): The board to convert into a plate
            layer_name (str): The layer name which represents the edge cutouts for the plate.
        """

        remove_board_items = []
        for track in board.GetTracks():
            remove_board_items.append(track)
        for zone in board.Zones():
            remove_board_items.append(zone)
        for drawing in board.GetDrawings():
            if (
                drawing.IsOnLayer(board.GetLayerID(layer_name))
                and drawing.GetClass() == "PCB_SHAPE"
            ):
                # Preserve graphic lines on target layer, and move them to layer edge cuts
                drawing.SetLayer(board.GetLayerID("Edge.Cuts"))
            elif drawing.IsOnLayer(board.GetLayerID("User.PlateSoldermask")):
                # Move to solder mask
                drawing.SetLayer(
                    board.GetLayerID("F.Mask")
                )  # Move to Front solder mask
                back_text = drawing.Duplicate()
                back_text.SetLayer(
                    board.GetLayerID("B.Mask")
                )  # Move to back solder mask
                board.Add(back_text)
            elif drawing.IsOnLayer(board.GetLayerID("User.PlateSilkscreen")):
                # Move text to silkscreen
                drawing.SetLayer(
                    board.GetLayerID("F.Silkscreen")
                )  # Move to Front Silkscreen
            else:
                # Delete all other graphics
                remove_board_items.append(drawing)

        # Remove the tracks/zones/drawings now that we are done iterating
        for remove_board_item in remove_board_items:
            board.Remove(remove_board_item)

        platebounds = board.GetBoardEdgesBoundingBox()

        # Convert footprints to NPTH pads and edge cuts
        for footprint in board.GetFootprints():
            if footprint.GetBoundingBox().Intersects(platebounds):
                footprint.Reference().SetVisible(False)
                footprint.Value().SetVisible(False)
                if re.match(r"^(H|LOGO)\d+$", footprint.GetReference()):
                    # Preserve pads on 'H' (mounting hole) and 'LOGO' (graphics) footprints
                    continue
                else:
                    remove_footprint_items = []
                    for (
                        pad
                    ) in (
                        footprint.Pads()
                    ):  # Convert SMD circle/oval pads on target layer to NPTH pads, and remove all other pads
                        if pad.IsOnLayer(
                            board.GetLayerID(layer_name)
                        ) and pad.GetShape() in [
                            pcbnew.PAD_SHAPE_CIRCLE,
                            pcbnew.PAD_SHAPE_OVAL,
                        ]:
                            drill_shape = (
                                pcbnew.PAD_DRILL_SHAPE_CIRCLE
                                if pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE
                                else pcbnew.PAD_DRILL_SHAPE_OBLONG
                            )
                            pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
                            pad.SetDrillShape(drill_shape)
                            pad.SetDrillSize(pad.GetSize())
                            pad.SetLayerSet(pad.UnplatedHoleMask())
                            pad.SetPosition(pad.GetPosition())
                        else:
                            remove_footprint_items.append(pad)
                    for (
                        graphic
                    ) in (
                        footprint.GraphicalItems()
                    ):  # Convert graphics on target layer to edge cuts, and remove all other graphics
                        if graphic.IsOnLayer(board.GetLayerID(layer_name)):
                            graphic.SetLayer(
                                board.GetLayerID("Edge.Cuts")
                            )  # Move target layer graphics to edge cuts
                        else:
                            remove_footprint_items.append(graphic)
                    # Remove the pads/graphics now that we are done iterating
                    for remove_footprint_item in remove_footprint_items:
                        footprint.Remove(remove_footprint_item)
                    if (
                        len(footprint.Pads()) == 0
                        and len(footprint.GraphicalItems()) == 0
                    ):
                        remove_board_items.append(footprint)
            else:
                remove_board_items.append(footprint)

        # Remove the footprints now that we are done iterating
        for remove_board_item in remove_board_items:
            board.Remove(remove_board_item)

        board.Save(board.GetFileName())

    @staticmethod
    def __copy_board(board_source_path, board_destination_path):
        """
        Creates a copy of the board at the source path and saves it to the destination path.

        Args:
            board_source_path (str): Path to the source .kicad_pcb file
            board_destination_path (str): Path to the destination .kicad_pcb file

        Returns:
            pcbnew.BOARD: The board object for the newly-copied board
        """
        shutil.copy(board_source_path, board_destination_path)
        return pcbnew.LoadBoard(board_destination_path)

    @staticmethod
    def produce():
        """
        Executes the board production on the currently-opened board.
        """
        current_board_path = pcbnew.GetBoard().GetFileName()

        try:
            relative_output_path = "../../gerbers"
            relative_temp_path = "../../temp"
            (board_folder, board_filename) = os.path.split(current_board_path)
            temp_path = os.path.normpath(os.path.join(board_folder, relative_temp_path))
            output_path = os.path.normpath(
                os.path.join(board_folder, relative_output_path)
            )

            if os.path.exists(temp_path):
                shutil.rmtree(temp_path)

            os.makedirs(temp_path)

            if not os.path.exists(output_path):
                os.makedirs(output_path)

            main_board = PiFinderBoardProducer.__copy_board(
                current_board_path, os.path.join(temp_path, board_filename)
            )
            bottom_plate = PiFinderBoardProducer.__copy_board(
                current_board_path,
                os.path.join(
                    temp_path,
                    board_filename.replace(".kicad_pcb", "-bottom-plate.kicad_pcb"),
                ),
            )
            PiFinderBoardProducer.__create_plate_pcb_from_layer(
                bottom_plate, "B.Adhesive"
            )
            top_plate = PiFinderBoardProducer.__copy_board(
                current_board_path,
                os.path.join(
                    temp_path,
                    board_filename.replace(".kicad_pcb", "-top-plate.kicad_pcb"),
                ),
            )
            PiFinderBoardProducer.__create_plate_pcb_from_layer(top_plate, "F.Adhesive")

            generated_file_list = []

            for pcb in [main_board, bottom_plate, top_plate]:
                if pcb.GetBoardEdgesBoundingBox().GetArea() > 0:
                    (board_folder, board_filename) = os.path.split(pcb.GetFileName())
                    (board_name, _) = os.path.splitext(board_filename)
                    gerber_output_path = os.path.join(temp_path, board_name)
                    archive_file_path = os.path.join(output_path, board_name)
                    PiFinderBoardProducer.__create_gerbers(pcb, gerber_output_path)
                    PiFinderBoardProducer.__create_drill_file(pcb, gerber_output_path)
                    generated_file = PiFinderBoardProducer.__create_zip(
                        archive_file_path, gerber_output_path
                    )
                    generated_file_list.append(generated_file)

            complete_dialog = wx.MessageDialog(
                None,
                "Boards produced successfully.\n\nGenerated files:\n"
                + "\n".join(generated_file_list),
                "Horizon Board Producer - Complete",
                wx.OK,
            )
            complete_dialog.ShowModal()
            complete_dialog.Destroy()
        finally:
            # HACK: In KiCad 6 (as of 6.0.4), calling method `pcbnew.LoadBoard` on a board other than the one belonging to the current project
            # undesirably mutates the application's current project context. To work around this, attempt to reload the current project.
            settings_manager = pcbnew.GetSettingsManager()
            settings_manager.LoadProject(
                current_board_path.replace(".kicab_pcb", ".kicad_pro"), False
            )


PiFinderBoardProducer().register()
