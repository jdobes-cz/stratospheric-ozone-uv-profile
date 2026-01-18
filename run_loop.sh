#!/bin/bash

rm -f loop/eup_*km.dat
rm -f loop/run_*km.inp

for z in $(seq 0 1 40); do
  echo "Running for z = $z km"
  sed "s/^zout_sea .*/zout_sea $z/" uvspec_template.inp > loop/run_${z}km.inp
  echo '# lambda[nm] zout[km] sza[deg] eup[W m-2 nm-1]' > loop/eup_${z}km.dat
  libRantran/libRadtran-2.0.6/bin/uvspec < loop/run_${z}km.inp | tr -d '\r' | grep -v '^[[:space:]]*$' >> loop/eup_${z}km.dat
done

wait

echo "All jobs finished"
