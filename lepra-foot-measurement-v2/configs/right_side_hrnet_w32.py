KEYPOINT_NAMES = [
    'pternion',
    'arch_low',
    'met1',
    'met1_apex',
    'toe_tip',
    'foot_leg_jxn',
    'lateral_malleolus',
    'heel_base',
]

KEYPOINT_COLORS = [
    [255, 0, 0],
    [0, 255, 0],
    [0, 0, 255],
    [255, 255, 0],
    [255, 0, 255],
    [0, 255, 255],
    [255, 128, 0],
    [128, 0, 255],
]

SKELETON = [[1, 2], [2, 3], [3, 5], [3, 4], [4, 6], [6, 1], [6, 7], [1, 8]]

NUM_KEYPOINTS = len(KEYPOINT_NAMES)

dataset_info = dict(
    dataset_name='foot_landmarks_8kp',
    keypoint_info={
        i: dict(name=name, id=i, color=color)
        for i, (name, color) in enumerate(zip(KEYPOINT_NAMES, KEYPOINT_COLORS))
    },
    skeleton_info={
        i: dict(
            link=(KEYPOINT_NAMES[a - 1], KEYPOINT_NAMES[b - 1]),
            id=i,
            color=[255, 255, 255],
        )
        for i, (a, b) in enumerate(SKELETON)
    },
    joint_weights=[1.0] * NUM_KEYPOINTS,
    sigmas=[0.025] * NUM_KEYPOINTS,
)

# 1. MODEL SETTINGS
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
        init_cfg=dict(
            type='Pretrained',
            checkpoint='https://download.openmmlab.com/mmpose/pretrain_models/hrnet_w32-36af842e.pth',
        ),
    ),
    head=dict(
        type='HeatmapHead',
        in_channels=32,
        out_channels=NUM_KEYPOINTS,
        deconv_out_channels=None,
        loss=dict(type='KeypointMSELoss', use_target_weight=True),
        decoder=dict(
            type='MSRAHeatmap',
            input_size=(256, 256),
            heatmap_size=(64, 64),
            sigma=2)
    ),
    test_cfg=dict(flip_test=False, shift_heatmap=True)
)

# 2. DATASET SETTINGS
dataset_type = 'CocoDataset'
data_root = 'data/with_malleolus/'

train_pipeline = [
    dict(type='LoadImage'),
    dict(type='GetBBoxCenterScale'),
    dict(type='RandomBBoxTransform'),
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
        ann_file='annotations/train.json',
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
        ann_file='annotations/val.json',
        data_prefix=dict(img='images/'),
        test_mode=True,
        pipeline=val_pipeline,
    )
)

test_dataloader = val_dataloader


# 4. RUNTIME
val_evaluator = dict(
    type='CocoMetric',
    ann_file=data_root + 'annotations/val.json'
)
test_evaluator = val_evaluator


optim_wrapper = dict(
    type='OptimWrapper',
    optimizer=dict(type='Adam', lr=5e-4),
)

param_scheduler = [
    dict(type='LinearLR', begin=0, end=100, by_epoch=False, start_factor=0.1),
    dict(type='MultiStepLR', begin=0, end=150, by_epoch=True, milestones=[90, 120], gamma=0.1),
]

train_cfg = dict(by_epoch=True, max_epochs=150, val_interval=10)
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

work_dir = './work_dirs/foot_hrnet_w32_8kp'
