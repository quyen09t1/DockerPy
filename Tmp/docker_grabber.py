'''
Created on Jan 29, 2016

@author: quyen
'''

import threading
import time


try:
    import docker
except ImportError as e:
    print ("Docker library not found ({0})".format(e))
    docker_tag = False
else:
    docker_tag = True

class Plugin():
    def __init__(self, args=None):
        
        self.args = args
        
        self.docker_client = False
        
        self.thread_list = {}
        
    def exit(self):
        print ("Stop the Docker plugin")
        for t in self.thread_list.values():
            t.stop()

    def get_key(self):
        return 'name'
    
    def connect(self, version=None):
        try:
            if version is None:
                ret = docker.Client(base_url="unix://var/run/docker.sock")
            else:
                ret = docker.Client(base_url="unix://var/run/docker.sock", version=version)
        except NameError:
            return None
        try:
            ret.version()
        except Exception as e:
            print ("Cannot connect to Docker server")
            ret = None
            
        if ret is None:
            print ("Docker plugin is disable because an error has been detected")
        return ret
    
    def reset(self):
        self.stats = {}
        
    def update(self):
        self.reset()
        self.input_method = 'local'
        if not self.docker_client:
            self.docker_client = self.connect()
            if self.docker_client is None:
                global docker_tag
                docker_tag = False
                
        if not docker_tag or (self.args is not None and self.args.disable_docker):
            return self.stats
        
        if self.input_method == 'local':
            try:
                self.stats['version'] = self.docker_client.version()
            except Exception as e:
                print "Cannot get Docker version"
                return self.stats
            
            try:
                self.stats['containers'] = self.docker_client.containers() or []
            except Exception as e:
                print "Cannot get containers list"
                return self.stats
            
            for container in self.stats['containers']:
                if container['Id'] not in self.thread_list:
                    print ("Create thread for container {0}.".format(container['Id'][:12]))
                    t = ThreadDockerGrabber(self.docker_client, container['Id'])
                    self.thread_list[container['Id']] = t 
                    t.start()
                
            nonexisting_containers = list(set(self.thread_list.keys()) - set([c['Id'] for c in self.stats['containers']]))
            for container_id in nonexisting_containers:
                print ("Stop thread for old container {0}".format(container_id[:12]))
                self.thread_list[container_id].stop()
                del(self.thread_list[container_id])
                
            for container in self.stats['containers']:
                container['key'] = self.get_key()
                container['name'] = container['Names'][0][1:]
                
                container['cpu'] = self.get_docker_cpu(container['Id'], self.thread_list[container['Id']].stats)
                container['memory'] = self.get_docker_memory(container['Id'], self.thread_list[container['Id']].stats)
                container['network'] = self.get_docker_network(container['Id'], self.thread_list[container['Id']].stats)
                container['io'] = self.get_docker_io(container['Id'], self.thread_list[container['Id']].stats)
                
        elif self.input_method == 'snmp':
            pass
        
        return self.stats
    
    def get_docker_cpu(self, container_id, all_stats):
        cpu_new = {}
        ret = {'total': 0.0}
        
        try:
            cpu_new['total'] = all_stats['cpu_stats']['cpu_usage']['total_usage']
            cpu_new['system'] = all_stats['cpu_stats']['system_cpu_usage']
            cpu_new['nb_core'] = len(all_stats['cpu_stats']['cpu_usage']['percpu_usage'])
        except KeyError as e:
            print ("Cannot grab CPU usage for container {0} ({1})".format(container_id, e))
        else:
            if not hasattr(self, 'cpu_old'):
                self.cpu_old = {}
                try:
                    self.cpu_old[container_id] = cpu_new
                except (IOError, UnboundLocalError):
                    pass
                
            if container_id not in self.cpu_old:
                try:
                    self.cpu_old[container_id] = cpu_new
                except (IOError, UnboundLocalError):
                    pass
            else:
                cpu_delta = float(cpu_new['total'] - self.cpu_old[container_id]['total'])
                system_delta = float(cpu_new['system'] - self.cpu_old[container_id]['system'])
                if cpu_delta > 0.0 and system_delta > 0.0:
                    ret['total'] = (cpu_delta / system_delta) * float(cpu_new['nbcore']) * 100
                self.cpu_old[container_id] = cpu_new    
        return ret
    
    def get_docker_memory(self, container_id, all_stats):
        ret = {}
        try:
            ret['rss'] = all_stats['memory_stats']['stats']['rss']
            ret['cache'] = all_stats['memory_stats']['stats']['cache']
            ret['usage'] = all_stats['memory_stats']['usage']
            ret['max_usage'] = all_stats['memory_stats']['max_usage']
        except KeyError as e:
            print ("Cannot grab MEM usage for container {0} ({1})".format(container_id, e))
            
        return ret
    
    def get_docker_network(self, container_id, all_stats):
        network_new = {}
        
        try:
            netcounters = all_stats['network']
        except KeyError as e:
            print ("Cannot grab NET usage for container {0} ({1})".format(container_id, e))
            
        return network_new
    
        if not hasattr(self, 'inetcounters_old'):
            self.netcounters_old = {}
            try:
                self.netcounters_old[container_id] = netcounters
            except (IOError, UnboundLocalError):
                pass
            
        if container_id not in self.netcounters_old:
            try:
                self.netcounters_old[container_id] = netcounters
            except (IOError, UnboundLocalError):
                pass
        else:
#             network_new['time_since_update'] = getTimeSinceLastUpdate("docker_net_{0}".format(container_id))
            network_new['rx'] = netcounters['rx_bytes'] - self.netcounters_old[container_id]['rx_bytes']
            network_new['tx'] = netcounters['tx_bytes'] - self.netcounters_old[container_id]['tx_bytes']
            network_new['cumulative_rx'] = netcounters['rx_bytes']
            network_new['cumulative_tx'] = netcounters['tx_bytes']
            
            self.netcounters_old[container_id] = netcounters
        
        return network_new
    
    def get_docker_io(self, container_id, all_stats):
        
        io_new = {}
        
        try:
            iocounters = all_stats['blkio_stats']
        except KeyError as e:
            print ("Cannot grab block IO usage for container {0} ({1})".format(container_id, e))
            return io_new
         
        if not hasattr(self, 'iocounters_old'):
            self.iocounters_old = {}
            try:
                self.iocounters_old[container_id] = iocounters
            except (IOError, UnboundLocalError):
                pass
            
        if container_id not in self.iocounters_old:
            try:
                self.iocounters_old[container_id] = iocounters
            except (IOError, UnboundLocalError):
                pass
        else:
            try:
                ior = [i for i in iocounters['io_service_bytes_recursive'] if i['op'] == 'Read'][0]['value']
                iow = [i for i in iocounters['io_service_bytes_recursive'] if i['op'] == 'Write'][0]['value']
                ior_old = [i for i in self.iocounters_old[container_id]['io_service_bytes_recursive'] if i['op'] == 'Read'][0]['value']
                iow_old = [i for i in self.iocounters_old[container_id]['io_service_bytes_recursive'] if i['op'] == 'Write'][0]['value'] 
            except (IndexError, KeyError) as e:
                print ("Cannot grab block IO usage for container {0} ({1})".format(container_id, e))
            else:
                io_new['ior'] = ior - ior_old
                io_new['iow'] = iow - iow_old
                io_new['cumulative_ior'] = ior
                io_new['cumulative_iow'] = iow
                
                self.iocounters_old[container_id] = iocounters
                
        return io_new       
        
class ThreadDockerGrabber(threading.Thread):
    def __init__(self, docker_client, container_id):
        print ("Create thread for container {0}".format(container_id[:12]))
        super(ThreadDockerGrabber, self).__init__()
        
        self._stopper = threading.Event()
        
        self._container_id = container_id
        self._stats_stream = docker_client.stats(container_id, decode=True)
        
        self._stats = {}
        self._notSet = True
        
    def run(self):
       
        for i in self._stats_stream:
            self._stats = i
            self._notSet = False
            time.sleep(0.1)
            if self.stopped():
                break
            
    @property
    def stats(self):
        
        while self._notSet:
            pass 
        return self._stats
    
    @stats.setter
    def stats(self, value):
        self._stats = value
        
    def stop(self, timeout=None):
        print ("Close thread for container {0}".format(self._container_id[:12]))
        self._stopper.set()
        
    def stopped(self):
        return self._stopper.isSet()
            