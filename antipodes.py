#!/usr/bin/env python3
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "fiona",
#     "shapely",
# ]
# ///
"""
Same as previous script but robust to different Natural Earth
attribute names (name / NAME / ADMIN, iso_a3 / ISO_A3 / ADM0_A3).
"""
import json
import argparse
from shapely.geometry import shape, mapping, Polygon, MultiPolygon, GeometryCollection, LineString
from shapely.ops import transform, unary_union, split
from shapely import errors as shapely_errors
import fiona

# ---------------------------------------------------------------------
def wrap_to_contiguous(g):
    g = transform(lambda x,y,z=None: ([xx if xx>=0 else xx+360 for xx in x], y), g)
    if g.bounds[2]-g.bounds[0] > 180:
        g = transform(lambda x,y,z=None: ([xx-360 if xx>180 else xx for xx in x], y), g)
    return g

def antipode(g):
    g = wrap_to_contiguous(g)
    g = transform(lambda x,y,z=None: ([(xx+180)%360 for xx in x], [-yy for yy in y]), g)
    return wrap_to_contiguous(g).buffer(0)

def split_antimeridian(poly):
    if poly.bounds[2]-poly.bounds[0] <= 180:
        return [poly]
    shifted = transform(lambda x,y,z=None: ([xx if xx>=0 else xx+360 for xx in x], y), poly)
    parts = split(shifted, LineString([(180,-90),(180,90)])).geoms
    return [transform(lambda x,y,z=None: ([xx-360 if xx>180 else xx for xx in x], y), p) for p in parts]

def polygons(g):
    if isinstance(g, Polygon):
        yield g
    elif isinstance(g, (MultiPolygon, GeometryCollection)):
        for geom in g.geoms:
            if isinstance(geom, Polygon):
                yield geom

# helper to read desired property
def get_prop(props, *keys):
    for k in keys:
        if k in props and props[k]:
            return props[k]
    return None

def build_antipodal_ocean(countries, landmask, erode_deg=0.15):
    sea_mask = landmask.buffer(-erode_deg).buffer(0)
    feats=[]
    for rec in countries:
        anti = antipode(rec['geom'])
        try:
            sea = anti.difference(sea_mask)
        except shapely_errors.TopologicalError:
            sea = anti.buffer(0).difference(sea_mask.buffer(0))
        if sea.is_empty:
            continue
        for poly in polygons(sea):
            for part in split_antimeridian(poly):
                part=part.buffer(0)
                if not part.is_empty and part.is_valid:
                    feats.append({
                        "type":"Feature",
                        "properties":{"orig_name":rec['name'],"orig_iso_a3":rec['iso']},
                        "geometry": mapping(part)
                    })
    return feats

def main():
    parser = argparse.ArgumentParser(description="Generate antipodal ocean GeoJSON.")
    parser.add_argument("--src", default="ne_110m_admin_0_countries", help="Path to Natural Earth shapefile")
    parser.add_argument("--dest", default="antipodal_ocean.geojson", help="Output GeoJSON")
    parser.add_argument("--erode", type=float, default=0.15, help="Landmask erosion in degrees")
    args = parser.parse_args()

    countries=[]
    with fiona.open(args.src) as src:
        for feat in src:
            props = feat["properties"]
            name = get_prop(props, "name", "NAME", "ADMIN")
            iso  = get_prop(props, "iso_a3", "ISO_A3", "ADM0_A3")
            if name is None: name = "unknown"
            if iso is None: iso = "UNK"
            countries.append({"name":name, "iso":iso, "geom": shape(feat["geometry"])})

    landmask = unary_union([c["geom"] for c in countries])
    features = build_antipodal_ocean(countries, landmask, args.erode)

    out = {"type":"FeatureCollection",
           "crs":{"type":"name","properties":{"name":"EPSG:4326"}},
           "features":features}
    with open(args.dest,"w") as f: json.dump(out, f, separators=(',',':'))
    print(f"✅  Wrote {len(features)} features → {args.dest}")

if __name__ == "__main__":
    main()
