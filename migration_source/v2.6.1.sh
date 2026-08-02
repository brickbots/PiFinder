# Keep POSIX shared memory alive across SSH logouts: logind's default
# RemoveIPC=yes deletes all IPC owned by the pifinder user (including the
# solver's cedar-detect /dev/shm segment) the moment that user's last login
# session ends — the PiFinder services run as pifinder but hold no login
# session of their own, so a plain SSH logout used to degrade solving until
# restart. The solver also recovers in software (PFCedarDetectClient), but
# this keeps the fast shared-memory handoff in place. Mirrors the same
# drop-in written by pifinder_setup.sh for fresh installs.
sudo mkdir -p /etc/systemd/logind.conf.d
printf '[Login]\nRemoveIPC=no\n' | sudo tee /etc/systemd/logind.conf.d/pifinder-removeipc.conf
# Apply without waiting for a reboot; harmless if logind isn't running.
# (Restarting logind does not end sessions, and RemoveIPC only acts at
# session end, so nothing is reaped by the restart itself.)
sudo systemctl try-restart systemd-logind.service || true
