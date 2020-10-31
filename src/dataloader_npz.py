import glob
import os.path as osp
import random
import sys
import time

import lmdb
import pyarrow as pa
import torch.utils.data as data
import copy

import numpy as np
from src.dataloader_utils import SeqFlip, DrawFromProbabilityMatrix, MaskRandomSubset, convert_seq_to_onehot, \
    convert_1d_features_to_2d, ConvertCoordToDists


class Dataset_npz(data.Dataset):
    '''
    Reads a folder full of npz files, and treats its as a database.
    Expects the data to be packed as follows:
    (features, target, mask)
        features = (seq, pssm, entropy)
        target = (r1, r2, r3)

    '''
    def __init__(self, folder, seq_flip_prop=0.5, chan_out=3, feature_dim=1, i_seq=False, i_pssm=False, i_entropy=False, i_cov=False, i_cov_all=False, i_contact=False, inpainting=False):

        search_command = folder + "*.npz"
        npzfiles = [f for f in glob.glob(search_command)]
        self.folder = folder
        self.files = npzfiles

        self.Flip = SeqFlip(seq_flip_prop)
        self.chan_out = chan_out
        self.draw_seq_from_pssm = False
        self.draw = DrawFromProbabilityMatrix(fraction_of_seq_drawn=0.2)
        self.draw_prob = 0.5
        self.seq_mask = MaskRandomSubset()
        self.feature_dim = feature_dim
        self.i_seq = i_seq
        self.i_pssm = i_pssm
        self.i_entropy = i_entropy
        self.i_cov = i_cov
        self.i_cov_all = i_cov_all
        self.i_contact = i_contact
        self.inpainting = inpainting
        self.chan_in = self.calculate_chan_in()
        self.coord_to_dist = ConvertCoordToDists()

    def calculate_chan_in(self):
        assert (self.i_cov is False or self.i_cov_all is False), "You can only have one of (i_cov, i_cov_all) = True"
        chan_in = 0
        if self.i_seq:
            chan_in += 20
        if self.i_pssm:
            chan_in += 21
        if self.i_entropy:
            chan_in += 1
        if self.inpainting:
            chan_in += 4 # 3 coordinates + 1 mask
        if self.feature_dim == 1:
            if self.i_cov_all:
                chan_in += 10*441
            elif self.i_cov:
                chan_in += 10*21
            if self.i_contact:
                chan_in += 20
        elif self.feature_dim == 2:
            chan_in *= 2
            if self.i_cov_all:
                chan_in += 441
            elif self.i_cov:
                chan_in += 21
            if self.i_contact:
                chan_in += 1
        print("Number of features used this run {:}".format(chan_in))
        return chan_in



    def __getitem__(self, index):
        data = np.load(self.files[index])
        coords = data['r1']

        features_1d = ()
        if self.i_seq:
            features_1d += (convert_seq_to_onehot(data['seq']),)
        if self.i_pssm:
            features_1d += (data['pssm'],)
        if self.i_entropy:
            features_1d += (data['entropy'],)
        if self.inpainting:
            r, m = self.seq_mask(coords)
            features_1d += (r,m[None,:],)

        if self.feature_dim == 1:
            if self.i_cov:
                cov = data['cov1d']
                cov = cov.reshape(-1,cov.shape[-1])
                features_1d += (cov,)
            if self.i_contact:
                contact = data['contact1d']
                features_1d += (contact.reshape(-1,contact.shape[-1]),)
            features = features_1d
        elif self.feature_dim == 2:
            features_2d = (convert_1d_features_to_2d(features_1d),)
            features_2d += (data['cov2d'],data['contact2d'][None,:,:],)
            features = features_2d

        features = np.concatenate(features, axis=0)

        self.Flip.reroll()
        features = self.Flip(features)
        coords = self.Flip(coords)
        coords = (coords,)

        distances = self.coord_to_dist(coords)

        return features, distances, coords

    def __len__(self):
        return len(self.files)


    def match_target_channels(self,target):
        if self.chan_out == 3:
            target = (target[0],)
        elif self.chan_out == 6:
            target = target[0:2]
        elif self.chan_out == 9:
            pass
        else:
            raise NotImplementedError("chan_out is {}, which is not implemented".format(self.chan_out))
        return target


    def __repr__(self):
        return self.__class__.__name__ + ' (' + self.folder + ')'
