"""
================================================================================

   Description: Testing integration between STAC of Sentinel-2 and SNS/Lambda

   Copyright (c) 2021, Alvaro Huarte - ahuarte47@yahoo.es. All rights reserved.

   Redistribution and use of this code in source and binary forms, with
   or without modification, are permitted provided that the following
   conditions are met:
   * Redistributions of source code must retain the above copyright notice,
     this list of conditions and the following disclaimer.
   * Redistributions in binary form must reproduce the above copyright notice,
     this list of conditions and the following disclaimer in the documentation
     and/or other materials provided with the distribution.

   THIS SAMPLE CODE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
   "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
   TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
   PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
   CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
   EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
   PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
   OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
   WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
   OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SAMPLE CODE, EVEN IF
   ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

================================================================================
"""

from osgeo import gdal
from osgeo import ogr


class OgrCommonUtils:
    """
    Provides utility functions of OGR library.
    """
    @staticmethod
    def create_geometry_from_bbox(x_min, y_min, x_max, y_max):
        """
        Returns the Geometry of the specified BBOX.
        """
        ring = ogr.Geometry(ogr.wkbLinearRing)
        ring.AddPoint(x_min, y_min)
        ring.AddPoint(x_max, y_min)
        ring.AddPoint(x_max, y_max)
        ring.AddPoint(x_min, y_max)
        ring.AddPoint(x_min, y_min)
        poly = ogr.Geometry(ogr.wkbPolygon)
        poly.AddGeometry(ring)
        return poly


class GdalCommonUtils:
    """
    Provides utility functions of GDAL library.
    """
    @staticmethod
    def get_envelope(dataset):
        """
        Get the spatial envelope of the GDAL dataset.
        """
        geo_transform = dataset.GetGeoTransform()
        c = geo_transform[0]
        a = geo_transform[1]
        b = geo_transform[2]
        f = geo_transform[3]
        d = geo_transform[4]
        e = geo_transform[5]
        t = 0  # Texel offset, by default the texel is centered to CENTER-CENTER pixel.
        col = 0
        row = 0
        env_a = [a * (col + t) + b * (row + t) + c, d * (col + t) + e * (row + t) + f]
        col = dataset.RasterXSize
        row = dataset.RasterYSize
        env_b = [a * (col + t) + b * (row + t) + c, d * (col + t) + e * (row + t) + f]
        min_x = min(env_a[0], env_b[0])
        min_y = min(env_a[1], env_b[1])
        max_x = max(env_a[0], env_b[0])
        max_y = max(env_a[1], env_b[1])
        return min_x, min_y, max_x, max_y

    @staticmethod
    def get_reading_window(dataset, bbox):
        """
        Calculates a window in pixel coordinates for which data will be read from a raster.
        """
        envelope = GdalCommonUtils.get_envelope(dataset)
        w = dataset.RasterXSize
        h = dataset.RasterYSize
        
        data_ul_x, data_lr_y = envelope[0], envelope[1]
        data_lr_x, data_ul_y = envelope[2], envelope[3]
        res_x = abs(data_ul_x - data_lr_x) / w
        res_y = abs(data_ul_y - data_lr_y) / h
        ul_x, lr_y = bbox[0], bbox[1]
        lr_x, ul_y = bbox[2], bbox[3]

        # If these coordinates wouldn't be rounded here, rasterio.io.DatasetReader.read would round them in the same way
        top = round((data_ul_y - ul_y) / res_y)
        left = round((ul_x - data_ul_x) / res_x)
        bottom = round((data_ul_y - lr_y) / res_y)
        right = round((lr_x - data_ul_x) / res_x)
        return left, top, right, bottom

    @staticmethod
    def rasterize_geometries(dataset, spatial_ref, geometry_type, geometries):
        """
        Rasterize the specified geometries to a GDAL dataset.
        """
        attribute_name = 'my_field'
        f_count = 0
        
        temp_store = ogr.GetDriverByName('Memory').CreateDataSource('wrk')
        temp_layer = temp_store.CreateLayer('temp', spatial_ref, geometry_type)
        temp_field = ogr.FieldDefn(attribute_name, ogr.OFTInteger)
        temp_layer.CreateField(temp_field)
        schema_def = temp_layer.GetLayerDefn()
        
        # Saving the geometries of interest to a temporary Feature Layer to rasterize.
        for geometry in geometries:
            feature = ogr.Feature(schema_def)
            feature.SetField(attribute_name, 1)
            feature.SetGeometry(geometry.Clone())
            temp_layer.CreateFeature(feature)
            feature = None
            f_count = f_count + 1

        # Render Features!
        errcode = gdal.RasterizeLayer(dataset, [1], temp_layer, options=['ATTRIBUTE={}'.format(attribute_name)])
        dataset.FlushCache()
        temp_field = None
        schema_def = None
        temp_layer = None
        temp_store = None
        return dataset
