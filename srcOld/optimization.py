import time

import matplotlib
import numpy as np

from srcOld.utils import move_tuple_to
from srcOld.visualization import compare_distogram, plotcoordinates, plotfullprotein

# from torch_lr_finder import LRFinder

matplotlib.use('Agg')

import torch

def train(net,optimizer,dataloader_train,loss_fnc,LOG,device='cpu',dl_test=None,ite=0,max_iter=100000,report_iter=1e4,checkpoint=1e19, scheduler=None):
    '''
    Standard training routine.
    :param net: Network to train
    :param optimizer: Optimizer to use
    :param dataloader_train: data to train on
    :param loss_fnc: loss function to use
    :param LOG: LOG file handler to print to
    :param device: device to perform computation on
    :param dataloader_test: Dataloader to test the accuracy on after each epoch.
    :param epochs: Number of epochs to train
    :return:
    '''
    stop_run = False
    net.to(device)
    t0 = time.time()
    t1 = time.time()
    loss_train_d = 0
    loss_train_ot = 0
    loss = 0
    # lr_finder = LRFinder(net, optimizer, loss_fnc, device=device)
    # lr_finder.range_test(dataloader_train, end_lr=100, num_iter=100)
    # lr_finder.plot()  # to inspect the loss-learning rate graph
    # lr_finder.reset()  # to reset the model and optimizer to their initial state




    while True:
        for i,(seq, target,mask, coords) in enumerate(dataloader_train):
            seq = seq.to(device, non_blocking=True)
            mask = mask.to(device, non_blocking=True)
            target = move_tuple_to(target, device, non_blocking=True)
            coords = move_tuple_to(coords, device, non_blocking=True)
            optimizer.zero_grad()
            outputs, coords_pred = net(seq,mask)
            loss_cnn, cnn_pred,cnn_target = OT(coords_pred[:,0:3,:], coords[0])
            loss_caa, caa_pred,caa_target = OT(coords_pred[:,3:6,:], coords[1])
            loss_cbb, cbb_pred,cbb_target = OT(coords_pred[:,6:9,:], coords[2])
            loss_d = loss_fnc(outputs, target)
            loss_c = loss_cnn + loss_caa + loss_cbb

            if ite > 250:
                loss = loss_d + loss_c
            else:
                loss = loss_d

            loss.backward()
            optimizer.step()
            loss_train_d += loss_d.cpu().detach()
            loss_train_ot += loss_c.cpu().detach()
            if scheduler is not None:
                scheduler.step()

            if (ite + 1) % report_iter == 0:
                if dl_test is not None:
                    t2 = time.time()
                    # loss_v = eval_net(net, dl_test, loss_fnc, device=device)
                    t3 = time.time()
                    if scheduler is None:
                        lr = optimizer.param_groups[0]['lr']
                    else:
                        lr = scheduler.get_last_lr()[0]
                    LOG.info(
                        '{:6d}/{:6d}  Loss(training): {:6.4f}%   Loss(test): {:6.4f}%  LR: {:.8}  Time(train): {:.2f}  Time(test): {:.2f}  Time(total): {:.2f}  ETA: {:.2f}h'.format(
                            ite + 1,int(max_iter), loss_train_d/report_iter*100, loss_train_ot/report_iter*100, lr, t2-t1, t3 - t2, t3 - t0,(max_iter-ite+1)/(ite+1)*(t3-t0)/3600))
                    t1 = time.time()
                    # plotcoordinates(pred, target_coord)
                    loss_train_d = 0
                    loss_train_ot = 0
            if (ite + 1) % checkpoint == 0:
                pass
                # filename = "{}{}_checkpoint.tar".format(save, ite + 1)
                # save_checkpoint(ite + 1, net.state_dict(), optimizer.state_dict(), filename=filename)
                # LOG.info("Checkpoint saved: {}".format(filename))
            ite += 1
            if ite >= max_iter:
                stop_run = True
                break
        if stop_run:
            break
    plotfullprotein(cnn_pred, caa_pred, cbb_pred, cnn_target, caa_target, cbb_target)
    # plotcoordinates(pred, target_coord)
    return net


def eval_net(net, dl, loss_fnc, device='cpu'):
    '''
    Standard training routine.
    :param net: Network to train
    :param optimizer: Optimizer to use
    :param dataloader_train: data to train on
    :param loss_fnc: loss function to use
    :param device: device to perform computation on
    :param dataloader_test: Dataloader to test the accuracy on after each epoch.
    :param epochs: Number of epochs to train
    :return:
    '''
    net.to(device)
    net.eval()
    with torch.no_grad():
        loss_v = 0
        for i,(seq, target, mask) in enumerate(dl):
            seq = seq.to(device, non_blocking=True)
            mask = mask.to(device, non_blocking=True)
            target = move_tuple_to(target, device, non_blocking=True)

            output = net(seq,mask)
            loss = loss_fnc(output, target)
            loss_v += loss.cpu().detach()
    compare_distogram(output, target)

    net.train()
    return loss_v



def OT(r1,r2):
    '''
    We try to do optimal transport of a point cloud into a reference point cloud.
    The transport is done with translation and rotation only.
    '''

    #r2 gives the mask
    mask = r2 != 0
    nb = r1.shape[0]

    r1s = r1[mask].reshape(nb,3,-1)
    r2s = r2[mask].reshape(nb,3,-1)

    #First we translate the two sets, by setting both their centroids to origin
    r1centroid = torch.mean(r1s,dim=2)
    r2centroid = torch.mean(r2s,dim=2)

    r1c = r1s - r1centroid[:,:,None]
    r2c = r2s - r2centroid[:,:,None]

    H = r1c @ r2c.transpose(1,2)

    #R = torch.matrix_power(H.transpose(1,2) @ H,0.5) @ torch.inverse(H)
    U, S, V = torch.svd(H)

    d = torch.det(V @ U.transpose(1,2))

    tt = torch.tensor([1, 1, d])
    tmp = torch.diag_embed(tt).to(device=V.get_device())
    R = V @ tmp @ U.transpose(1,2)

    tt2 = torch.tensor([1, 1, -d])
    tmp2 = torch.diag_embed(tt2).to(device=V.get_device())
    R2 = V @ tmp2 @ U.transpose(1,2)

    r1c_rotated = R @ r1c
    r1c_rotated2 = R2 @ r1c

    assert torch.norm(r2c) > 0
    res1 = torch.norm(r1c_rotated - r2c) ** 2 / torch.norm(r2c) ** 2
    res2 = torch.norm(r1c_rotated2 - r2c) ** 2 / torch.norm(r2c) ** 2


    # dr11 = r1c_rotated[:,:,1:] - r1c_rotated[:,:,:-1]
    # dr12 = r1c_rotated2[:,:,1:] - r1c_rotated2[:,:,:-1]
    # dr2 = r2c[:,:,1:] - r2c[:,:,:-1]
    #
    # dres1 = torch.norm(dr11 - dr2) ** 2 / torch.norm(dr2) ** 2
    # dres2 = torch.norm(dr12 - dr2) ** 2 / torch.norm(dr2) ** 2


    if res1 < res2:
        res = res1
        # dres = dres1
        pred = r1c_rotated.squeeze().cpu().detach().numpy()

    else:
        pred = r1c_rotated2.squeeze().cpu().detach().numpy()
        res = res2
        # dres = dres2
    result = res #+ dres
    # print("result = {:2.2f}, result2 = {:2.2f}".format(result,result2))

    target = r2c.squeeze().cpu().detach().numpy()

    return result, pred,target