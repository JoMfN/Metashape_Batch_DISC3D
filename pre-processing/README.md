## Preprocessing of DISC3D scans 
For the script to work, we require the working directory structure in the format of:

```
Inputs per scan folder:
  <Datetime>__<uid>__<Species>__DISC3D/
    ├─ <uid>__edof/*.png
    ├─ <Datetime>__<uid>__<Species>__CamPos.txt      (not used; XML has the reference)
    └─ models/<dataset>_Calibrated_Cameras_*.xml     (existing calibrated cameras)
```

In the case of our setup we have 396 `.png` images in the `<uid>__edof` subfolder of a scan. 

Some prepreparation tools will be uploaded later. Important is to have datetime in the folder name of a scan as well as for the subfolder __edof and the specific Camera Position file that has the reference coordinates of each of the images. 

