import os
import supervisely_lib as sly

import numpy as np

my_app = sly.AppService()

task_id = os.environ["TASK_ID"]
TEAM_ID = int(os.environ['context.teamId'])
WORKSPACE_ID = int(os.environ['context.workspaceId'])
PROJECT_ID = int(os.environ['modal.state.slyProjectId'])
REMOVE_ORIGINAL_CLASS = bool(os.environ['modal.state.remove'])




@my_app.callback("do")
@sly.timeit
def do(**kwargs):
    api = sly.Api.from_env()

    # read source project
    src_project = api.project.get_info_by_id(PROJECT_ID)

    if src_project.type != str(sly.ProjectType.IMAGES):
        raise RuntimeError("Project {!r} has type {!r}. App works only with type {!r}"
                           .format(src_project.name, src_project.type, sly.ProjectType.IMAGES))

    src_project_meta_json = api.project.get_meta(src_project.id)
    src_project_meta = sly.ProjectMeta.from_json(src_project_meta_json)

    # create destination project
    DST_PROJECT_NAME = "{} (without AnyShape)".format(src_project.name)

    dst_project = api.project.create(WORKSPACE_ID, DST_PROJECT_NAME, description="without AnyShape",
                                     change_name_if_conflict=True)
    sly.logger.info('Destination project is created.',
                    extra={'project_id': dst_project.id, 'project_name': dst_project.name})

    dst_project_meta = sly.ProjectMeta()

    def convert_annotation(src_ann):
        new_labels = []
        for idx, lbl in enumerate(src_ann.labels):
            lbl: sly.Label

            if lbl.obj_class.geometry_type == sly.AnyGeometry:
                figure_geometry = type(lbl.geometry)

                new_class_name = "{}_{}".format(lbl.obj_class.name, figure_geometry.geometry_name())
                new_class = dst_project_meta.get_obj_class(new_class_name)
                if new_class is None:
                    new_class = sly.ObjClass(name=new_class_name, geometry_type=figure_geometry, color=sly.color.generate_rgb())
                    pass
            else:
                pass



            cur_obj_class = lbl.obj_class
            new_cls = dst_project_meta.obj_classes.get(lbl.obj_class.name)
            if not need_convert(lbl.obj_class.geometry_type):
                new_lbl = lbl.clone(obj_class=new_cls)
                new_labels.append(new_lbl)
            else:
                if allow_render_non_spatial_for_any_shape(lbl) == False:
                    continue
                mask = common_img == idx
                if np.any(mask):  # figure may be entirely covered by others
                    g = lbl.geometry
                    new_bmp = sly.Bitmap(data=mask,
                                         labeler_login=g.labeler_login,
                                         updated_at=g.updated_at,
                                         created_at=g.created_at)
                    new_lbl = lbl.clone(geometry=new_bmp, obj_class=new_cls)
                    new_labels.append(new_lbl)

        return src_ann.clone(labels=new_labels)
        pass

    for ds_info in api.dataset.get_list(src_project.id):
        ds_progress = sly.Progress('Processing dataset: {!r}/{!r}'.format(src_project.name, ds_info.name),
                                   total_cnt=ds_info.images_count)
        dst_dataset = api.dataset.create(dst_project.id, ds_info.name)
        img_infos_all = api.image.get_list(ds_info.id)

        for img_infos in sly.batched(img_infos_all):
            img_names, img_ids, img_metas = zip(*((x.name, x.id, x.meta) for x in img_infos))

            ann_infos = api.annotation.download_batch(ds_info.id, img_ids)
            anns = [sly.Annotation.from_json(x.annotation, src_project_meta) for x in ann_infos]

            new_anns = [convert_annotation(ann) for ann in anns]

            new_img_infos = api.image.upload_ids(dst_dataset.id, img_names, img_ids, metas=img_metas)
            new_img_ids = [x.id for x in new_img_infos]
            api.annotation.upload_anns(new_img_ids, new_anns)

            ds_progress.iters_done_report(len(img_infos))

    api.task.set_output_project(task_id, dst_project.id, dst_project.name)


def main():
    my_app = sly.AppService()
    my_app.run(initial_events=[{"command": "do"}])
    my_app.wait_all()


if __name__ == "__main__":
    sly.main_wrapper("main", main)