import napalm as npm
import time
import json
import threading
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from drawnow import *

# create a driver
driver = npm.get_network_driver('ios')

# semaphore
p_lock = threading.Lock()

# gobal dataset
dataset = pd.DataFrame()  # columns=['timestamp', 'hostname', 'cpu', 'mem'])

ro_tseries = {}


# list of all SSH accessible IP addresses

def init_param():
    ip_list = ['192.168.182.140', '192.168.182.141', '192.168.182.142']
    uname = 'rishi'
    passwd = 'Pass123..'
    sec = 'cisco123'
    router_obj_list = []
    # create a routre Object
    for ip in ip_list:
        router_obj_list.append(driver(hostname=ip,
                                      username=uname,
                                      password=passwd,
                                      optional_args={'secret': 'cisco123'})
                               )

    return router_obj_list


def connect_daemon(ro):
    try:
        ro.open()
        temp = ro.get_facts()
        print(f"Connection to {temp['vendor']} {temp['model']} Successfull... !")
    except:
        print('Waiting For Connection Response...')


def open_conn_MT(router_obj_list):
    thread_list = []
    for ro in router_obj_list:
        thread_list.append(threading.Thread(target=connect_daemon, args=(ro,)))
    for th in thread_list:
        th.start()
    for th in thread_list:
        th.join()


def get_util(router_obj):
    temp = router_obj.get_environment()
    cpu = temp['cpu'][0]['%usage']
    mem = round(int(temp['memory']['used_ram']) / int(temp['memory']['available_ram']), 3)
    return {'cpu': cpu, 'mem': mem}


'fetch metadata of a router (ro) given as Router_object'


def get_cost(bw, dly, rly, tload, rload, k_val=[0.25, 0.25, 0.25, 0.25]):
    kb = k_val[0]
    kd = k_val[1]
    kr = k_val[2]
    kl = k_val[3]

    term1 = 1 - kl * (tload + rload) / 2
    term2 = kb * bw * kd * dly
    term3 = kr * rly

    return term1 * term2 * term3


def gen_router_metadata(ro):
    facts = ro.get_facts()
    ip_intf = ro.get_interfaces_ip()

    ro_menifest = {
        'host': facts["hostname"],
        'model': facts["model"],
        'util': get_util(ro),  # {'cpu' : c_util , 'mem' : m_util}
        'intf': {}
    }

    ip_intf_list = ip_intf.keys()

    # fetch Metric Information for each active interface
    for intf in ip_intf_list:
        cmd = [f'sh int {intf} | inc MTU',
               f'sh int {intf} | inc load']

        temp_bdm = ro.cli([cmd[0]])[cmd[0]].split(' ')
        temp_rll = ro.cli([cmd[1]])[cmd[1]].split(' ')

        ro_menifest['intf'][intf] = {'ip': list(ip_intf[intf]["ipv4"])[0],
                                     'bw': int(temp_bdm[4]),
                                     'dly': int(temp_bdm[7]),
                                     'mtu': int(temp_bdm[1]),
                                     'rly': round(eval(temp_rll[1])[0], 3),
                                     'tld': round(eval(temp_rll[3])[0], 3),
                                     'rld': round(eval(temp_rll[5]), 3)
                                     }
        ro_menifest['intf'][intf]['cost'] = get_cost(bw=ro_menifest['intf'][intf]['bw'],
                                                     dly=ro_menifest['intf'][intf]['dly'],
                                                     rly=ro_menifest['intf'][intf]['rly'],
                                                     tload=ro_menifest['intf'][intf]['tld'],
                                                     rload=ro_menifest['intf'][intf]['rld']
                                                     )

    return ro_menifest


def gen_TSeries(menifest):
    global dataset
    # print(time.time(),menifest['host'],menifest['util']['cpu'],menifest['util']['mem'])

    fixed_col = ['timestamp', 'hostname', 'cpu', 'mem']
    cost_list = []

    for intf in menifest['intf'].keys():
        cost_list.append(menifest['intf'][intf]['cost'])

    entry = [int(time.time()),
             menifest['host'],
             menifest['util']['cpu'],
             menifest['util']['mem']
             ] + cost_list

    mergd_cols = fixed_col + list(menifest['intf'].keys())

    row = pd.DataFrame([entry], columns=mergd_cols)
    # print(row)

    with p_lock:
        dataset = dataset.append(row, ignore_index='True')  # merging two lists


def collector_daemon(ro, output):
    print('fetching...')
    menifest = gen_router_metadata(ro)
    if output:
        print(json.dumps(menifest, indent=4))
    else:
        print('\nSuccesully Feched!')
    gen_TSeries(menifest)


def Menifest_Collector_MT(ro_list, output):
    th_list = []

    for ro in ro_list:
        th_list.append(threading.Thread(target=collector_daemon, args=(ro, output,)))
    for th in th_list:
        th.start()
    for th in th_list:
        th.join()


def iterator_ds_fill(ro_list):
    while True:
        Menifest_Collector_MT(ro_list, output=False)
        time.sleep(2)


def iterator_ds_show():
    while True:
        try:
            for host in list(dataset['hostname'].unique()):
                print(f'\n hostname : {host}')
                print(dataset.loc[dataset['hostname'] == host])
        except:
            print('Dataset Not yet populated !!')
        time.sleep(2)


def plot_me():
    global ro_tseries

    try:
        for host in list(dataset['hostname'].unique()):
            ro_tseries[host] = {'cpu': [], 'mem': []}

        for host in list(dataset['hostname'].unique()):
            ro_tseries[host]['cpu'] = dataset.loc[dataset['hostname'] == host]['cpu'].tolist()
            ro_tseries[host]['mem'] = dataset.loc[dataset['hostname'] == host]['mem'].tolist()

        for host in ro_tseries.keys():
            y_cpu = ro_tseries[host]['cpu']
            y_mem = ro_tseries[host]['mem']
            x = np.arange(len(y_cpu))
            plt.scatter(x, y_cpu)
            plt.scatter(x, y_mem)

            plt.plot(x, y_cpu, ':', label=host + '_CPU%')
            plt.plot(x, y_mem, ':', label=host + '_Mem%')

        plt.grid(True)
        plt.legend()
    except:
        print('dataset not yet polulated ! ')
        print('dataset not yet polulated ! ')


def main_loop():
    while True:
        drawnow(plot_me)


def main():
    ro_list = init_param()
    open_conn_MT(ro_list)

    th_fill = threading.Thread(target=iterator_ds_fill, args=(ro_list,), name='th_fill')
    th_show = threading.Thread(target=iterator_ds_show, name='th_show')
    th_plot = threading.Thread(target=main_loop, name='th_plot')

    th_fill.start()
    th_show.start()
    th_plot.start()


main()
