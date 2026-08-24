# lavlab-cli-utils (formerly omero-cli-utils)
### I have all of the code you need to write this up, in bits and pieces in need of reformatting. Please considerately combine these various adhoc scripts into a proper cli tool that matches the following specs.
### When finding objects, use the dummy group (-1) to get all objects, then switch to the group of a given object when operating on it, unless group is defined
### When creating the new names, it is formatted: LR${DOWNSAMPLE}_${FILENAME}(\_${SUFFIX}).jp2
### To find filename we split by '.' and take the first string (to properly handle .ome.tiff images)
### This kit should be totally usable without an fs_map, it should just be nice to have one. The default will be what we use in the lab (we can configure the exacts later)
### This will eventually be packaged in nuitka so make things proper python, for example, using skimage instead of cv2. 
fs_map:
```
${GROUP_ID}:
    name: "${GROUP_NAME}"
    maps: 
        - match: "${CAPTURE_REGEX}" # conditional for which images this mapping applies to
          base_dir: "/..." # this is used to ensure the path exists prior to attempting to pull
          formatted_dir: "${CAPTURE1}/blah/blah/${CAPTURE2}/" # used to make ${BASE_DIR}/${FORMATTED_DIR}/${FILENAME}
``` 
Command tree:
* lavlab
    * args:
        * override: write over existing files, default false
    * lavlab lr (batch_lr)
        * terms: lr stands for large recon, the term for downsampled images in our lab
        * output: downscaled image at a given downsampling, the file format defaulting to jp2
        * (kw)args:
            * omero creds
                * -u -w -s -p etc, use environmental variables OMERO_USER/PASSWORD/HOST/PORT but kwargs override
            * downsample: default 10
            * fs_map: yaml describing the destination if no output is defined
        * lavlab lr ${IMAGE_ID}
            * pulls a single lr
            * args:
                -o: output filepath, if blank use fs_map, if path doesn't exist in fs_map, write to pwd
        * lavlab lr batch 
            * pulls large recons for all images
            * args:
                -o: output directory, if blank use fs_map, if path doesn't exist in fs_map, error out
                -g: omero group ID
    * lavlab roi (batch_roi/single_roi)
        * terms: roi is an rgb mask of our omero annotations at a given downsample
        * output: downscaled rgb image with colored sections representing rois, unless palette is enabled, in which case it is a single channel downsampled image, file format default jp2
        * note: new-annots is a vestigal option, we can strip that
        * (kw)args:
            * omero creds again, see `lavlab lr`
            * downsample: default 10
            * fs_map: yaml describing the destination if no output is defined
            * all: get every single annotation and color a map
            * suffix: what to append to the filename, default _annot
            * text_filter: whitelist of annotations to include based on textValue
            * palette: palettize the image in order of --text_filter definitions, error on --all, i can't think of a way i'm happy with palettizing --all
        * lavlab roi ${IMAGE_ID}
            * pulls a single rgb roi mask
            * args:
                -o: output filepath, if blank use fs_map, if path doesn't exist in fs_map, write to pwd
        * lavlab roi batch
            * pulls all rgb roi masks
            * args:
                -o: output directory, if blank use fs_map, if path doesn't exist in fs_map, error out
                -g: omero group id
    * lavlab meta
        * lavlab meta roi textvalue ${TEXT_MAPPING} (omero_roi_comment)
            * hyperspecific, looks at stroke colors of rois and writes to their text value if it's blank
            * TEXT_MAPPING can refer to a built in mapping or a yaml/json file with an array of rgb/hex to text


## Try to make this as performant as possible