{ pkgs, python ? pkgs.python313, astro-data }:
# The DB catalogs as numpy columns (python/PiFinder/catalog_arrays.py), built
# here in CI so a device never builds them.
#
# The only inputs are the objects DB (astro-data) and the three Python files
# the builder needs, so a normal code change does not rebuild the arrays or
# add a new store path to download. The app finds them through the
# `catalog_arrays` link in pifinder-src.
let
  pythonEnv = python.withPackages (ps: [ ps.numpy ]);
  builderSrc = pkgs.lib.fileset.toSource {
    root = ../../python/PiFinder;
    fileset = pkgs.lib.fileset.unions [
      ../../python/PiFinder/__init__.py
      ../../python/PiFinder/catalog_arrays.py
      ../../python/PiFinder/composite_object.py
      ../../python/PiFinder/utils.py
    ];
  };
in
pkgs.runCommand "pifinder-catalog-arrays" { nativeBuildInputs = [ pythonEnv ]; } ''
  # PiFinder.utils expects astro_data next to python/, as in the repo.
  mkdir -p tree/python/PiFinder
  cp ${builderSrc}/*.py tree/python/PiFinder/
  ln -s ${astro-data} tree/astro_data
  cd tree/python
  python -m PiFinder.catalog_arrays build \
    --db ${astro-data}/pifinder_objects.db --out ../arrays
  mv ../arrays $out
''
