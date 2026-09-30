//! Where the sun is, and which phase of the day that makes it.
//!
//! Wallpapers are labelled with the phases they suit (classify-sun.py in the
//! Wallpapers repo) and cycling only offers the ones matching the current
//! phase. Phases are defined by solar elevation rather than clock time, which
//! is what makes daylight wallpapers run longer in summer and shorter in winter
//! without any seasonal configuration.
//!
//! The position is the NOAA solar calculator's low-precision algorithm
//! (Meeus, Astronomical Algorithms). It is good to well under 0.1 degrees for
//! centuries either side of 2000, far finer than any phase boundary here.

use std::f64::consts::PI;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Phase {
    Night,
    Twilight,
    Golden,
    Day,
}

pub const PHASES: [Phase; 4] = [Phase::Night, Phase::Twilight, Phase::Golden, Phase::Day];

impl Phase {
    pub fn name(self) -> &'static str {
        match self {
            Phase::Night => "night",
            Phase::Twilight => "twilight",
            Phase::Golden => "golden",
            Phase::Day => "day",
        }
    }

    pub fn parse(text: &str) -> Option<Phase> {
        PHASES.into_iter().find(|phase| phase.name() == text.trim())
    }

    /// Position on the night..day axis, for "how many phases apart".
    pub fn rank(self) -> i32 {
        self as i32
    }

    /// Phase boundaries in degrees of solar elevation. The labelling prompt
    /// describes the same bands in words, so the two must move together:
    /// night is astronomical-ish darkness, twilight is the blue hour, golden
    /// is the sun on or just over the horizon.
    pub fn from_elevation(elevation: f64) -> Phase {
        if elevation < -12.0 {
            Phase::Night
        } else if elevation < -2.0 {
            Phase::Twilight
        } else if elevation < 8.0 {
            Phase::Golden
        } else {
            Phase::Day
        }
    }
}

fn rad(degrees: f64) -> f64 {
    degrees * PI / 180.0
}

fn deg(radians: f64) -> f64 {
    radians * 180.0 / PI
}

/// Geometric solar elevation in degrees (no refraction) at a point on Earth
/// at a Unix time.
pub fn elevation(latitude: f64, longitude: f64, unix_seconds: i64) -> f64 {
    let julian_day = unix_seconds as f64 / 86_400.0 + 2_440_587.5;
    let t = (julian_day - 2_451_545.0) / 36_525.0;

    let mean_longitude = (280.46646 + t * (36_000.76983 + t * 0.000_303_2)).rem_euclid(360.0);
    let mean_anomaly = 357.52911 + t * (35_999.05029 - 0.000_153_7 * t);
    let eccentricity = 0.016_708_634 - t * (0.000_042_037 + 0.000_000_126_7 * t);

    let m = rad(mean_anomaly);
    let center = m.sin() * (1.914_602 - t * (0.004_817 + 0.000_014 * t))
        + (2.0 * m).sin() * (0.019_993 - 0.000_101 * t)
        + (3.0 * m).sin() * 0.000_289;
    let true_longitude = mean_longitude + center;
    let omega = 125.04 - 1_934.136 * t;
    let apparent_longitude = true_longitude - 0.005_69 - 0.004_78 * rad(omega).sin();

    let mean_obliquity = 23.0 + (26.0 + (21.448 - t * (46.815 + t * (0.000_59 - t * 0.001_813))) / 60.0) / 60.0;
    let obliquity = mean_obliquity + 0.002_56 * rad(omega).cos();

    let declination = (rad(obliquity).sin() * rad(apparent_longitude).sin()).asin();

    let y = (rad(obliquity) / 2.0).tan().powi(2);
    let l0 = rad(mean_longitude);
    let equation_of_time = 4.0
        * deg(y * (2.0 * l0).sin() - 2.0 * eccentricity * m.sin()
            + 4.0 * eccentricity * y * m.sin() * (2.0 * l0).cos()
            - 0.5 * y * y * (4.0 * l0).sin()
            - 1.25 * eccentricity * eccentricity * (2.0 * m).sin());

    let utc_minutes = unix_seconds.rem_euclid(86_400) as f64 / 60.0;
    let true_solar_minutes = (utc_minutes + equation_of_time + 4.0 * longitude).rem_euclid(1_440.0);
    let hour_angle = rad(true_solar_minutes / 4.0 - 180.0);

    let lat = rad(latitude);
    let cos_zenith = lat.sin() * declination.sin() + lat.cos() * declination.cos() * hour_angle.cos();
    90.0 - deg(cos_zenith.clamp(-1.0, 1.0).acos())
}

#[cfg(test)]
mod tests {
    use super::*;

    const SEATTLE: (f64, f64) = (47.6062, -122.3321);

    #[test]
    fn summer_solstice_noon_is_high() {
        // 2024-06-20 20:11 UTC is Seattle's solar noon; 90 - 47.6 + 23.44.
        let e = elevation(SEATTLE.0, SEATTLE.1, 1_718_914_260);
        assert!((e - 65.8).abs() < 0.3, "{e}");
        assert_eq!(Phase::from_elevation(e), Phase::Day);
    }

    #[test]
    fn winter_sunrise_is_at_the_horizon() {
        // Published sunrise 2024-12-21 07:55 PST. Sunrise is defined at -0.83
        // degrees geometric (refraction plus the sun's radius).
        let e = elevation(SEATTLE.0, SEATTLE.1, 1_734_796_500);
        assert!((e + 0.83).abs() < 0.4, "{e}");
        assert_eq!(Phase::from_elevation(e), Phase::Golden);
    }

    #[test]
    fn equinox_evening_turns_from_twilight_to_night() {
        // 2024-03-20 03:00 UTC is 20:00 PDT, about forty minutes after sunset:
        // blue hour. Three hours later it is fully dark.
        let e = elevation(SEATTLE.0, SEATTLE.1, 1_710_903_600);
        assert!(e < -2.0 && e > -12.0, "{e}");
        assert_eq!(Phase::from_elevation(e), Phase::Twilight);
        let later = elevation(SEATTLE.0, SEATTLE.1, 1_710_903_600 + 3 * 3600);
        assert_eq!(Phase::from_elevation(later), Phase::Night);
    }

    #[test]
    fn summer_days_are_longer_than_winter_days() {
        let day_hours = |start: i64| {
            (0..24 * 60)
                .filter(|minute| {
                    let e = elevation(SEATTLE.0, SEATTLE.1, start + minute * 60);
                    Phase::from_elevation(e) == Phase::Day
                })
                .count() as f64
                / 60.0
        };
        let june = day_hours(1_718_866_800); // 2024-06-20 07:00 UTC, local midnight
        let december = day_hours(1_734_768_000); // 2024-12-21 08:00 UTC, local midnight
        assert!(june > 13.0 && december < 7.0, "june {june}h december {december}h");
    }

    #[test]
    fn phases_round_trip_by_name() {
        for phase in PHASES {
            assert_eq!(Phase::parse(phase.name()), Some(phase));
        }
        assert_eq!(Phase::parse("dusk"), None);
    }
}
