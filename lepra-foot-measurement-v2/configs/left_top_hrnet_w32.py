# Keypoint order MUST match data/annotations/left_top_*.json categories[0].keypoints.
# Same 6-keypoint schema as right_top_hrnet_w32.py — pternion is excluded
# because the heel posterior point is not visible from a top-down view.
#
# This config is a mirror of right_top_hrnet_w32.py (Apr 29 retrain) with
# the dataset name and ann_file paths changed for the left-foot dataset.
# Differences from the broken Feb 13 left_top config:
#   - 6 keypoints instead of 6: pternion removed, met5_apex added.
#   - RandomFlip removed: left-foot-only dataset, mirroring would invert
#     anatomy without corresponding label swaps. This was the root cause
#     of the prior model placing pternion in random locations.
#   - flip_test=False: same reason.
#   - sigmas=0.07 (was 0.025): hand-clicked foot landmarks have ~5px jitter,
#     COCO eye-level 0.025 was too strict and hid real progress.
#   - RandomBBoxTransform tuned: rotate ±40°, scale 0.75-1.25, shift 0.16.
#   - max_epochs 80 (was 150), milestones [50, 70], val_interval=5.
KEYPOINT_NAMES = [
    'toe_tip',        # 0: tip of longest toe
    'met1',           # 1: 1st metatarsal head
    'met1_apex',      # 2: highest point of 1st metatarsal head
    'met5_apex',      # 3: highest point of 5th metatarsal head
    'met5',           # 4: 5th metatarsal head
    'foot_leg_jxn',   # 5: where leg meets foot
]

KEYPOINT_COLORS = [
    [255, 0, 0],
    [0, 255, 0],
    [0, 0, 255],
    [255, 255, 0],
    [255, 0, 255],
    [0, 255, 255],
]

# Symmetric pairs declared for completeness only — flip is OFF in pipelines
# below because the dataset is left-foot-only.
FLIP_PAIRS = [(1, 4), (2, 3)]  # met1<->met5, met1_apex<->met5_apex

dataset_info = dict(
    dataset_name='foot_left_top',
    keypoint_info={
        i: dict(
            name=name,
            id=i,
            color=KEYPOINT_COLORS[i % len(KEYPOINT_COLORS)],
            type='',
            swap=KEYPOINT_NAMES[dict(FLIP_PAIRS + [(b, a) for a, b in FLIP_PAIRS]).get(i, i)]
                 if i in dict(FLIP_PAIRS + [(b, a) for a, b in FLIP_PAIRS]) else '',
        )
        for i, name in enumerate(KEYPOINT_NAMES)
    },
    skeleton_info=dict(),
    joint_weights=[1.0] * len(KEYPOINT_NAMES),
    sigmas=[0.07] * len(KEYPOINT_NAMES),
)

# 1. MODEL
model = dict(
    type='TopdownPoseEstimator',
    data_preprocessor=dict(
        type='PoseDataPreprocessor',
        mean=[123.675, 116.28, 103.53],
        std=[58.395, 57.12, 57.375],
        bgr_to_rgb=True),
    backbone=dict(
        type='HRNet',
        in_channels=3,
        extra=dict(
            stage1=dict(
                num_modules=1, num_branches=1, block='BOTTLENECK',
                num_blocks=(4, ), num_channels=(64, )),
            stage2=dict(
                num_modules=1, num_branches=2, block='BASIC',
                num_blocks=(4, 4), num_channels=(32, 64)),
            stage3=dict(
                num_modules=4, num_branches=3, block='BASIC',
                num_blocks=(4, 4, 4), num_channels=(32, 64, 128)),
            stage4=dict(
                num_modules=3, num_branches=4, block='BASIC',
                num_blocks=(4, 4, 4, 4), num_channels=(32, 64, 128, 256))),
    ),
    head=dict(
        type='HeatmapHead',
        in_channels=32,
        out_channels=len(KEYPOINT_NAMES),
        deconv_out_channels=None,
        loss=dict(type='KeypointMSELoss', use_target_weight=True),
        decoder=dict(
            type='MSRAHeatmap',
            input_size=(256, 256),
            heatmap_size=(64, 64),
            sigma=2)
    ),
    test_cfg=dict(flip_test=False, flip_mode='heatmap', shift_heatmap=True)
)

# 2. DATASET
dataset_type = 'CocoDataset'
data_root = 'data/'

train_pipeline = [
    dict(type='LoadImage'),
    dict(type='GetBBoxCenterScale'),
    # NO RandomFlip — left-foot-only dataset, no mirror partner.
    dict(type='RandomBBoxTransform',
         shift_factor=0.16, shift_prob=0.3,
         scale_factor=(0.75, 1.25), scale_prob=1.0,
         rotate_factor=40.0, rotate_prob=0.6),
    dict(type='TopdownAffine', input_size=(256, 256)),
    dict(
        type='GenerateTarget',
        encoder=dict(
            type='MSRAHeatmap',
            input_size=(256, 256),
            heatmap_size=(64, 64),
            sigma=2)),
    dict(type='PackPoseInputs')
]

val_pipeline = [
    dict(type='LoadImage'),
    dict(type='GetBBoxCenterScale'),
    dict(type='TopdownAffine', input_size=(256, 256)),
    dict(type='PackPoseInputs')
]

# 3. DATALOADERS
# Annotation file naming follows the right_top convention. If your left
# dataset uses different filenames, edit the three ann_file lines below.
train_dataloader = dict(
    batch_size=4,
    num_workers=2,
    pin_memory=True,
    persistent_workers=True,
    sampler=dict(type='DefaultSampler', shuffle=True),
    dataset=dict(
        type=dataset_type,
        data_root=data_root,
        metainfo=dataset_info,
        ann_file='annotations/left_top_train.json',
        data_prefix=dict(img='images/'),
        pipeline=train_pipeline,
    )
)

val_dataloader = dict(
    batch_size=4,
    num_workers=2,
    pin_memory=True,
    persistent_workers=True,
    drop_last=False,
    sampler=dict(type='DefaultSampler', shuffle=False, round_up=False),
    dataset=dict(
        type=dataset_type,
        data_root=data_root,
        metainfo=dataset_info,
        ann_file='annotations/left_top_val.json',
        data_prefix=dict(img='images/'),
        test_mode=True,
        pipeline=val_pipeline,
    )
)

test_dataloader = val_dataloader

# 4. EVAL / RUNTIME
val_evaluator = dict(
    type='CocoMetric',
    ann_file=data_root + 'annotations/left_top_val.json'
)
test_evaluator = val_evaluator

optim_wrapper = dict(
    type='OptimWrapper',
    optimizer=dict(type='Adam', lr=5e-4),
)

param_scheduler = [
    dict(type='LinearLR', begin=0, end=100, by_epoch=False, start_factor=0.1),
    dict(type='MultiStepLR', begin=0, end=80, by_epoch=True, milestones=[50, 70], gamma=0.1),
]

train_cfg = dict(by_epoch=True, max_epochs=80, val_interval=5)
val_cfg = dict()
test_cfg = dict()

default_scope = 'mmpose'
default_hooks = dict(
    timer=dict(type='IterTimerHook'),
    logger=dict(type='LoggerHook', interval=50),
    param_scheduler=dict(type='ParamSchedulerHook'),
    checkpoint=dict(type='CheckpointHook', interval=10, save_best='coco/AP', rule='greater'),
    sampler_seed=dict(type='DistSamplerSeedHook'),
)

work_dir = './work_dirs/left_top_hrnet_w32'

# Initialise from the COCO-pretrained HRNet-W32 backbone for fastest convergence.
# Set to a local .pth path if you have one; None starts from random weights.
load_from = None
