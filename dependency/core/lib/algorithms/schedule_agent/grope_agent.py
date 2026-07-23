import abc

from core.lib.common import ClassFactory, ClassType, Context, TaskConstant, LOGGER
from core.lib.content import Task

from .grope import ContextRecord, GropeScheduler

import copy

from .base_agent import BaseAgent

__all__ = ('GropeAgent',)


@ClassFactory.register(ClassType.SCH_AGENT, alias='grope')
class GropeAgent(BaseAgent, abc.ABC):



    def __init__(self, system, agent_id: int, sch_param: dict, grope_param: dict):

        super().__init__(system, agent_id)
        self.cur_resource_table = {}
        self.cur_scenario = {}
        self.cur_policy = {}
        self.cur_task = None

        self.agent_id = agent_id
        self.cloud_device = system.cloud_device
        self.edge_device = None
        self.service_names = None

        self.fps_list = system.fps_list
        self.resolution_list = system.resolution_list
        self.buffer_size_list = [x for x in system.buffer_size_list if x >= 2]
        self.edge_serv_num_list = None


        self.if_stop_record_in_single_cycle = sch_param['if_stop_record_in_single_cycle']
        self.stop_max_frame_num = sch_param['stop_max_frame_num']
        self.processed_frame_num = 0
        self.if_keep_record = True

        from datetime import datetime
        current_time = datetime.now()
        time_string = current_time.strftime("%Y-%m-%d-%H-%M-%S")

        self.record_path_prefix = Context.get_file_path(sch_param['record_path'])
        self.path_suffix =  str(agent_id) + '-online' + '-' + time_string + '.json'

        self.record_path = None

        self.init_param = grope_param
        self.init_param['context_names'] = ['band_Mbps', 'obj_num', 'obj_size_norm', 'obj_speed']
        self.init_param['kb_path'] = Context.get_file_path(grope_param['kb_path'])

        self.grope_scheduler = None

        self.grope_type = grope_param['grope_type']
    
    
    def run(self):
        pass

    def update_scenario(self, scenario):
        self.cur_scenario = scenario

    def update_resource(self, device, resource):
        self.cur_resource_table[device] = resource

    def update_policy(self, policy):
        self.cur_policy = policy

    def update_task(self, task: Task):
        if task == None:
            LOGGER.debug('New task is None.')
            return
        else:
            LOGGER.debug(f'New task id: {task.get_task_id()}')

        cur_task = copy.deepcopy(task)

        self.cur_task = cur_task
        self.update_record(cur_task=cur_task)
        LOGGER.debug('Finished updating the task record.')
        self.update_aware(cur_task=cur_task)
        LOGGER.debug('Finished updating scheduler awareness.')


    def update_record(self, cur_task: Task):
        task = copy.deepcopy(cur_task)
        if self.if_keep_record:
            LOGGER.debug('Task recording is enabled.')
            context_record = ContextRecord(
                task=task,
                resource_table=self.cur_resource_table
            )

            if self.record_path is None:
                self.record_path = self.record_path_prefix + '-' + 'source_id' + '-' + str(task.get_source_id()) + '-' + task.get_source_device() + '-' + self.path_suffix

            ContextRecord.write_record(context_record=context_record,
                                       file_path=self.record_path)
            LOGGER.debug('Wrote task record.')
        else:
            LOGGER.debug('Task recording is disabled.')

        if self.if_stop_record_in_single_cycle == 1:
            LOGGER.debug('Single-cycle recording stop is enabled.')
            self.processed_frame_num += self.get_logic_frame_num_from_task(cur_task=task)
            LOGGER.debug(
                f'Processed logic frames: {self.processed_frame_num}; '
                f'limit: {self.stop_max_frame_num}'
            )

            if self.processed_frame_num > self.stop_max_frame_num:
                LOGGER.debug('Logic frame limit reached; stop recording.')
                self.if_keep_record = False
        else:
            LOGGER.debug('Single-cycle recording stop is disabled.')

    
    def update_aware(self, cur_task: Task):

        pass

    def get_schedule_plan(self, info):

        new_schedule_plan = None

        if self.edge_device is None:
            self.edge_device = info['source_device']

        if self.edge_serv_num_list is None or self.service_names is None:
            pipeline_dict = Task.extract_pipeline_deployment_from_dag_deployment(info['dag'])
            self.service_names = []
            for service_info in pipeline_dict:
                if service_info['service_name'] not in (TaskConstant.START.value, TaskConstant.END.value):
                    self.service_names.append(service_info['service_name'])
            self.edge_serv_num_list = [i for i in range(0, len(self.service_names) + 1)]

    
        if self.grope_scheduler is None:

            raw_meta_data = info['meta_data']

            adjusted_delay_cons = self.init_param['delay_cons'] * self.init_param['delay_cons_adjust']
            adjusted_acc_cons = self.init_param['acc_cons'] * self.init_param['acc_cons_adjust']

            self.grope_scheduler = GropeScheduler(
                kb_path=self.init_param['kb_path'],
                service_name_pipeline=self.service_names,
                knob_value_range_dict={
                    'fps': self.fps_list,
                    'resolution': self.resolution_list,
                    'buffer_size': self.buffer_size_list,
                    'edge_serv_num': self.edge_serv_num_list
                },
                delay_cons=adjusted_delay_cons,
                acc_cons=adjusted_acc_cons,
                delay_weight=self.init_param['delay_weight'],
                acc_weight=self.init_param['acc_weight'],
                default_policy=self.init_param['default_policy'],
                raw_meta_data=raw_meta_data,
                grope_type_param = self.init_param['grope_type_param'],
                goal_type = self.init_param['goal_type'],
                corrector_param=self.init_param['corrector_param'],
                queue_param=self.init_param['queue_param'],
            )

        task = copy.deepcopy(self.cur_task)
        task_id = None
        cur_policy = None
        context_info = None

        if task is not None:
            task_id = task.get_task_id()
            cur_policy = self.get_conf_info_from_task(cur_task=task)
            context_info = self.get_context_info_from_task(cur_task=task)

        # cur_task_id, cur_policy, context_info, grope_type
        new_policy = self.grope_scheduler.get_schedule_plan(cur_task_id=task_id,
                                                            cur_policy = cur_policy,
                                                            context_info = context_info,
                                                            grope_type = self.grope_type
                                                            )
        old_pipeline_dict = Task.extract_pipeline_deployment_from_dag_deployment(info['dag'])
        new_pipeline_dict = self.trans_edge_serv_num_to_pipeline_dict(edge_serv_num=new_policy['edge_serv_num'],
                                                                        pipeline_dict=old_pipeline_dict,
                                                                        edge_device=self.edge_device,
                                                                        cloud_device=self.cloud_device)
        new_dag = Task.extract_dag_deployment_from_pipeline_deployment(new_pipeline_dict)

        new_schedule_plan = {
            'fps': new_policy['fps'],
            'resolution': new_policy['resolution'],
            'buffer_size': new_policy['buffer_size'],
            'dag': new_dag,
            'encoding': 'mp4v'
        }

        return new_schedule_plan






   
    def get_delay_from_task(self, cur_task: Task):

        task = copy.deepcopy(cur_task)
        exe_delay = 0
        edge_cloud_trans_delay = 0
        if_found_patition = False

        pipeline_dict = task.get_pipeline_deployment_info()
        metadata = task.get_metadata()
        raw_metadata = task.get_raw_metadata()
        dag = task.get_dag()

        for service_info in pipeline_dict:
            if service_info['service_name'] not in (TaskConstant.START.value, TaskConstant.END.value):
                service = dag.get_node(service_info['service_name']).service
                exe_delay += service.get_execute_time()
            if service_info['service_name'] not in (TaskConstant.START.value, TaskConstant.END.value):
                service = dag.get_node(service_info['service_name']).service
                if service.get_execute_device() == self.cloud_device:
                    if not if_found_patition:
                        edge_cloud_trans_delay = service.get_transmit_time()
                        if_found_patition = True

        avg_delay = (exe_delay + edge_cloud_trans_delay) / metadata['buffer_size']
        raw_fps = raw_metadata['fps']
        conf_fps = metadata['fps']
        avg_delay *= (conf_fps / raw_fps)

        return avg_delay

    def get_logic_frame_num_from_task(self, cur_task: Task):
        task = copy.deepcopy(cur_task)
        metadata = task.get_metadata()
        raw_metadata = task.get_raw_metadata()
        buffer_size = metadata['buffer_size']
        fps_ratio = raw_metadata['fps'] / metadata['fps']
        logic_frame_num = buffer_size * fps_ratio
        return logic_frame_num

    def get_context_info_from_task(self, cur_task: Task):
        task = copy.deepcopy(cur_task)
        context_num = 0
        context_info = {}
        if self.edge_device != None:
            if self.edge_device in self.cur_resource_table:
                if 'available_bandwidth' in self.cur_resource_table[self.edge_device]:
                    context_info['band_Mbps'] = self.cur_resource_table[self.edge_device]['available_bandwidth']
                    context_num += 1
        if task != None:
            scenario_data = task.get_first_scenario_data()
            tmp_data = task.get_tmp_data()
            scenario_data['file_size'] = tmp_data['file_size']

            if 'obj_size' in scenario_data and 'obj_num' in scenario_data and 'obj_velocity' in scenario_data:
                if (len(scenario_data['obj_num']) > 0):
                    context_info['obj_size_norm'] = sum(scenario_data['obj_size']) / len(scenario_data['obj_size'])
                    context_info['obj_num'] = sum(scenario_data['obj_num']) / len(scenario_data['obj_num'])
                else:
                    context_info['obj_size_norm'] = 0
                    context_info['obj_num'] = 0
                context_info['obj_speed'] = scenario_data['obj_velocity']
                context_num += 3

        if context_num == 4:
            return context_info
        else:
            return None

    def get_conf_info_task_info_from_task(self, cur_task: Task):

        conf_info = self.get_conf_info_from_task(cur_task=cur_task)
        task_info = self.get_task_info_from_task(cur_task=cur_task)

        return conf_info, task_info

    def get_conf_info_from_task(self, cur_task: Task):

        task = copy.deepcopy(cur_task)

        if task == None:
            return None

        metadata = task.get_metadata()
        pipeline_dict = task.get_pipeline_deployment_info()

        conf_info = {}
        conf_info['resolution'] = metadata['resolution']
        conf_info['fps'] = metadata['fps']
        conf_info['buffer_size'] = metadata['buffer_size']
        conf_info['edge_serv_num'] = self.trans_pipeline_dict_to_edge_serv_num(pipeline_dict=pipeline_dict,
                                                                               cloud_device=self.cloud_device)

        return conf_info

    def get_task_info_from_task(self, cur_task: Task):

        task = copy.deepcopy(cur_task)

        if task == None:
            return None

        task_info = {}
        pipeline_dict = task.get_pipeline_deployment_info()
        metadata = task.get_metadata()
        dag = task.get_dag()
        edge_cloud_trans_delay = 0
        if_found_patition = False

        service_num = 0
        for service_info in pipeline_dict:

            if service_info['service_name'] not in (TaskConstant.START.value, TaskConstant.END.value):
                service_num += 1
                service = dag.get_node(service_info['service_name']).service
                exe_delay = (service.get_real_execute_time()) / metadata['buffer_size']
                wait_delay = - exe_delay + ((service.get_execute_time()) / metadata['buffer_size'])

                if service_num == 1:
                    task_info['real_exe_detect'] = exe_delay
                    task_info['detect_wait_delay'] = wait_delay
                elif service_num == 2:
                    task_info['real_exe_classify'] = exe_delay
                    task_info['classify_wait_delay'] = wait_delay

            if service_info['service_name'] not in (TaskConstant.START.value, TaskConstant.END.value):
                service = dag.get_node(service_info['service_name']).service
                if service.get_execute_device() == self.cloud_device:
                    if not if_found_patition:
                        edge_cloud_trans_delay = service.get_transmit_time() / metadata['buffer_size']
                        if_found_patition = True

        task_info['task_id'] = task.get_task_id()
        task_info['real_trans'] = edge_cloud_trans_delay

        LOGGER.debug(f'task_info: {task_info}')

        return task_info

    def trans_edge_serv_num_to_pipeline_dict(self, edge_serv_num, pipeline_dict, edge_device, cloud_device):
        if pipeline_dict[0]['service_name'] == TaskConstant.START.value:
            edge_serv_num += 1
        pipeline_dict = [{**p, 'execute_device': edge_device} for p in pipeline_dict[:edge_serv_num]] + \
                        [{**p, 'execute_device': cloud_device} for p in pipeline_dict[edge_serv_num:]]
        return pipeline_dict

    def trans_pipeline_dict_to_edge_serv_num(self, pipeline_dict, cloud_device):
        edge_serv_num = 0
        for service_info in pipeline_dict:
            if service_info['service_name'] not in (TaskConstant.START.value, TaskConstant.END.value) and \
                service_info['execute_device'] != cloud_device:
                edge_serv_num += 1
            else:
                break
        return edge_serv_num
