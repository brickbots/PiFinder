attach `/home/pifinder/PiFinder/astro_data/observations.db` as ad_obs;
attach `/home/pifinder/PiFinder_data/observations.db` as pfd_obs;
BEGIN;
insert into pfd_obs.obs_sessions(start_time_local, lat, lon, timezone, UID)
select start_time_local, lat, lon, timezone, UID from ad_obs.obs_sessions;
insert into pfd_obs.obs_objects(session_uid, obs_time_local, catalog, sequence, solution, notes)
select session_uid, obs_time_local, catalog, sequence, solution, notes from ad_obs.obs_objects;
COMMIT;
.exit
