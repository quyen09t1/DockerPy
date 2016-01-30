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
#             try:
#                 self.stats['version'] = self.docker_client.version()
#             except Exception as e:
#                 print "Cannot get Docker version"
#                 return self.stats
            
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
    
        
class ThreadDockerGrabber(threading.Thread):
    def __init__(self, docker_client, container_id):
        print ("Create thread for container {0}".format(container_id[:12]))
        super(ThreadDockerGrabber, self).__init__()
        
        self._stopper = threading.Event()
        
        self._container_id = container_id
        self._stats_stream = docker_client.stats(container_id, decode=True)
        print self._stats_stream
        self._stats = {}
        
    def run(self):
        print "run"
        for i in self._stats_stream:
            self._stats = i
            time.sleep(0.1)
            if self.stopped():
                break
            
    @property
    def stats(self):
        time.sleep(1)
        return self._stats
    
    @stats.setter
    def stats(self, value):
        self._stats = value
        
    def stop(self, timeout=None):
        print ("Close thread for container {0}".format(self._container_id[:12]))
        self._stopper.set()
        
    def stopped(self):
        return self._stopper.isSet()
            