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

import json
import os
import numpy as np
import boto3

from osgeo import gdal
from osgeo import ogr
from osgeo import osr
from osgeo_utils import OgrCommonUtils, GdalCommonUtils
from file_utils import FileUtils

gdal.UseExceptions()
gdal.SetConfigOption('GDAL_DISABLE_READDIR_ON_OPEN', 'TRUE')
gdal.SetConfigOption('CPL_CURL_VERBOSE', 'NO')
gdal.SetConfigOption('CPL_DEBUG', 'NO')
gdal.SetConfigOption('CPL_VSIL_CURL_ALLOWED_EXTENSIONS', '.tif')


def get_valid_sen2cor_cloud_mask(cm_raster, valid_classes=[2, 4, 5, 6, 7, 11]):
    """
    Returns the valid sen2cor SCL mask (SCL: 2,4,5,6,7,11 are valid, otherwise are cloudy).
    """
    scl_mask = np.zeros_like(cm_raster, dtype=np.bool)
    for code in valid_classes: scl_mask = np.logical_or(scl_mask, (cm_raster == code).astype(np.bool))
    return scl_mask


def get_valid_sigpac_urban_mask(lu_raster, valid_classes=[0, 5]):
    """
    Returns the valid Urban-type mask (SIGPAC: 0,5 are urban-type polygons).
    """
    lu_mask = np.zeros_like(lu_raster, dtype=np.bool)
    for code in valid_classes: lu_mask = np.logical_or(lu_mask, (lu_raster == code).astype(np.bool))
    return lu_mask


def print_statistics(label, array):
    """
    Print some statistics of the specified numpy array.
    """
    unique_vals = np.unique(array)
    unique_count = [np.count_nonzero(array == v) for v in unique_vals]
    percentages = [100.0 * (v / array.size) for v in unique_count]
    print('INFO: {}: shape={} size={} min={} max={} unique={} count={} %={}'.format(label, array.shape, array.size, array.min(), array.max(), unique_vals, unique_count, percentages))

def lambda_handler(event, context):
    """
    Lambda function to calculate Statistics of Cloud Coverage in S2L2A products
    """
    #print('GDAL_VERSION={}'.format(gdal.VersionInfo()))
    #print('EventObj={}'.format(json.dumps(event)))
    
    # Get environment settings.
    lu_dataset_path = os.environ['LANDUSE_DATASET_S3_PATH']
    output_folder = os.environ['OUTPUT_S3_FOLDER']
    # Get overlapping grid names with my input Dataset.
    # https://sentinel.esa.int/web/sentinel/missions/sentinel-2/data-products
    grid_names = os.environ['S2L2A_TILES'].split(',')
    
    # Get Metadata of current Product.
    message_obj = json.loads(event['Records'][0]['Sns']['Message'])
    item_id = message_obj['id']
    properties = message_obj['properties']
    assets = message_obj['assets']
    
    product_id = properties['sentinel:product_id']
    platform = properties['platform']
    utm_zone = properties['sentinel:utm_zone']
    latitude = properties['sentinel:latitude_band']
    grid_square = properties['sentinel:grid_square']
    product_date = item_id[10:18]
    cloud_cover = properties['eo:cloud_cover']
    print('INFO: ProductId={}, ItemId={}, Platform={}, GridName={}{}{}, Date={}, CloudCover={}'.format(product_id, item_id, platform, utm_zone, latitude, grid_square, product_date, cloud_cover))
    
    geog_crs = osr.SpatialReference()
    geog_crs.ImportFromEPSG(4326)
    grid_crs = osr.SpatialReference()
    grid_crs.ImportFromEPSG(32630)
    transform = osr.CoordinateTransformation(geog_crs, grid_crs)
    
    geometry_as_text = str(message_obj['geometry'])
    geometry = ogr.CreateGeometryFromJson(geometry_as_text)
    print(' + Geometry={}, EPSG=4326'.format(str(geometry)))
    geometry.Transform(transform)
    print(' + Geometry={}, EPSG=32630'.format(str(geometry)))
    
    # Open the S2L2A SCL/CloudMask raster.
    cm_object_path = '/vsicurl/{}'.format(assets['SCL']['href'])
    print(' + CloudMask ObjectPath={}'.format(cm_object_path))
    cm_dataset = gdal.Open(cm_object_path, gdal.GA_ReadOnly)
    cm_extent = GdalCommonUtils.get_envelope(cm_dataset)
    cm_geometry = OgrCommonUtils.create_geometry_from_bbox(cm_extent[0], cm_extent[1], cm_extent[2], cm_extent[3])
    cm_band = cm_dataset.GetRasterBand(1)
    print(' + Envelope=({}), RasterSize=({},{}), GdalType={}'.format(cm_extent, cm_dataset.RasterXSize, cm_dataset.RasterYSize, cm_band.DataType))
    cm_band = None
    
    # Open the LandUse Dataset.
    lu_object_path = lu_dataset_path.replace('s3://', '/vsis3/')
    print('INFO: LandUse ObjectPath={}'.format(lu_object_path))
    lu_dataset = gdal.Open(lu_object_path, gdal.GA_ReadOnly)
    lu_extent = GdalCommonUtils.get_envelope(lu_dataset)
    lu_geometry = OgrCommonUtils.create_geometry_from_bbox(lu_extent[0], lu_extent[1], lu_extent[2], lu_extent[3])
    lu_band = lu_dataset.GetRasterBand(1)
    print(' + Envelope=({}), RasterSize=({},{}), GdalType={}'.format(lu_extent, lu_dataset.RasterXSize, lu_dataset.RasterYSize, lu_band.DataType))
    lu_band = None
    
    # If input layers do not intersect, do not process anything.
    if not lu_geometry.Intersects(cm_geometry):
        return {
            'statusCode': 200,
            'body': json.dumps('Input data do not intersect')
        }
        
    s3 = boto3.client('s3')
    
    # Calculate geometry of AOI...
    aoi_geometry = cm_geometry.Intersection(lu_geometry)
    # ... subtracting geometries of already processed tiles, we do not want to process pixels twice.
    for grid_name in grid_names:
        item_name = item_id[0:4] + grid_name + item_id[9:]
        item_path = os.path.join(output_folder, item_name + '.json')
        print(' + ItemName={}, Exist={} Current={}'.format(item_name, FileUtils.exist_s3_path(s3, item_path), item_name==item_id))
        
        if item_name != item_id and FileUtils.exist_s3_path(s3, item_path):
            bucket_name, prefix_path = FileUtils.parse_s3_path(item_path)
            s3_response = s3.get_object(Bucket = bucket_name, Key = prefix_path)
            s3_content = s3_response['Body']
            item_obj = json.loads(s3_content.read())
            temp_env = item_obj['land_use']['aoi_extent']
            geom_obj = OgrCommonUtils.create_geometry_from_bbox(temp_env[0], temp_env[1], temp_env[2], temp_env[3])
            #print(' - ItemObjt={}'.format(json.dumps(item_obj)))
            if aoi_geometry.Intersects(geom_obj): aoi_geometry = aoi_geometry.Difference(geom_obj)
            
    temp_x_min, temp_x_max, temp_y_min, temp_y_max = aoi_geometry.GetEnvelope()
    aoi_x_min = max(temp_x_min, lu_extent[0])
    aoi_y_min = max(temp_y_min, lu_extent[1])
    aoi_x_max = min(temp_x_max, lu_extent[2])
    aoi_y_max = min(temp_y_max, lu_extent[3])
    aoi_extent = [aoi_x_min, aoi_y_min, aoi_x_max, aoi_y_max]
    print('INFO: IOU Envelope={}'.format(aoi_extent))
    
    # Get raster data from input Datasets.
    left, top, right, bottom = GdalCommonUtils.get_reading_window(cm_dataset, aoi_extent)
    print(' + CloudMask Dataset Window=({},{},{},{}) Size=({},{})'.format(left, top, right, bottom, right-left, bottom-top))
    cm_band = cm_dataset.GetRasterBand(1)
    cm_no_data = cm_band.GetNoDataValue()
    cm_raster = cm_band.ReadAsArray(xoff=left, yoff=top, win_xsize=right-left, win_ysize=bottom-top)
    cm_band = None
    left, top, right, bottom = GdalCommonUtils.get_reading_window(lu_dataset, aoi_extent)
    print(' + LandUse Dataset Window=({},{},{},{}) Size=({},{})'.format(left, top, right, bottom, right-left, bottom-top))
    lu_band = lu_dataset.GetRasterBand(1)
    lu_no_data = lu_band.GetNoDataValue()
    lu_raster = lu_band.ReadAsArray(xoff=left, yoff=top, win_xsize=right-left, win_ysize=bottom-top)
    lu_band = None
    
    num_decimals = 10 if grid_crs.IsGeographic() else 5
    resolution_x = round((cm_extent[2] - cm_extent[0]) / float(cm_dataset.RasterXSize), num_decimals)
    resolution_y = round((cm_extent[3] - cm_extent[1]) / float(cm_dataset.RasterYSize), num_decimals)
    print(' + NumDecimals={} Resolution=({}, {})'.format(num_decimals, resolution_x, resolution_y))
    
    # Clean resources.
    cm_dataset = None
    lu_dataset = None
    
    # Merge valid pixels from both input raster data.
    cm_raster = get_valid_sen2cor_cloud_mask(cm_raster)
    cm_raster = cm_raster.astype(np.int)
    lu_raster = get_valid_sigpac_urban_mask(lu_raster)
    lu_raster = lu_raster.astype(np.int)
    rs_raster = np.copy(lu_raster)
    valid_mask = ((cm_raster > 0) & (lu_raster > 0))
    rs_raster[valid_mask] = 2
    
    #print_statistics('cm_raster', cm_raster)
    #print_statistics('lu_raster', lu_raster)
    #print_statistics('rs_raster', rs_raster)
    
    # Clean resources.
    del cm_raster
    del lu_raster
    
    gm_raster_size_x = int((aoi_extent[2] - aoi_extent[0]) / resolution_x)
    gm_raster_size_y = int((aoi_extent[3] - aoi_extent[1]) / resolution_y)
    gm_no_data = 0
    
    # Rasterize Geometry of input valid CloudMask, we will mask with current result.
    driver = gdal.GetDriverByName('MEM')
    gm_dataset = driver.Create('', gm_raster_size_x, gm_raster_size_y, 1, gdal.GDT_Byte)
    gm_dataset.SetProjection(grid_crs.ExportToWkt())
    gm_dataset.SetGeoTransform([aoi_extent[0], resolution_x, 0.0, aoi_extent[3], 0.0, -resolution_y])
    gm_dataset.GetRasterBand(1).SetNoDataValue(gm_no_data)
    gm_dataset.FlushCache()
    GdalCommonUtils.rasterize_geometries(gm_dataset, grid_crs, ogr.wkbPolygon, [geometry])
    gm_dataset.FlushCache()
    gm_band = gm_dataset.GetRasterBand(1)
    gm_raster = gm_band.ReadAsArray()
    gm_band = None
    gm_dataset = None
    
    #print_statistics('gm_raster', gm_raster)
    
    # Calculate final results and save data.
    valid_mask = (gm_raster == 1)
    rs_raster[~valid_mask] = 0
    del gm_raster
    count_of_valid_urban_pixels = np.count_nonzero(rs_raster == 2)
    count_of_urban_pixels = np.count_nonzero(rs_raster > 0)
    del rs_raster
    urban_cover = (100.0 * count_of_valid_urban_pixels) / count_of_urban_pixels
    print('INFO: Urban pixels={}, Valid Urban pixels={}, Urban cover={}'.format(count_of_urban_pixels, count_of_valid_urban_pixels, urban_cover))
    
    message_obj['land_use'] = { 
        'urban_pixels': count_of_urban_pixels, 
        'valid_urban_pixels': count_of_valid_urban_pixels, 
        'urban_cover': urban_cover,
        'aoi_extent': cm_extent
    }
    
    # Save updated metadata of current STAC item to our Bucket.
    temp_file = '/tmp/{}.json'.format(item_id)
    with open(temp_file, 'w', encoding='utf-8') as fp:
        json.dump(message_obj, fp)
        
    bucket_name, prefix_path = FileUtils.parse_s3_path(os.path.join(output_folder, item_id + '.json'))
    s3.upload_file(temp_file, bucket_name, prefix_path)
    
    return {
        'statusCode': 200,
        'body': json.dumps('OK')
    }
