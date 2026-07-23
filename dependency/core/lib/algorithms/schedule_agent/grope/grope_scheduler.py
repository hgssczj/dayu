'''
说明：以下策略并不是其原本方法的标准实现，而是受其启发后根据本系统实际情况做出的权宜之计
例如Gecko原算法要求实现的、比较图像帧差异的算法搞不出来，于是用速度取而代之，用于表示不同图像之间的差异
此外，这些原始方法中若存在本系统不具备的配置旋钮，也一并舍弃了

'''

# 收获新的类
from .integrated_safe_predictor import IntegratedSafePredictor
from .dict_str_set import DictStrSet
import copy
import time
import math


class GropeScheduler:

    def __init__(self, 
                 kb_path, 
                 service_name_pipeline,
                 knob_value_range_dict, 
                 delay_cons,
                 acc_cons,
                 delay_weight,
                 acc_weight,
                 default_policy,
                 raw_meta_data,
                 grope_type_param,  #搜索类型
                 goal_type, #目标类型,prefer或者rigid，都是越大越好
                 corrector_param,
                 queue_param
                 ):
        

        self.cur_task_id = -1 #当前已经收到的、执行完毕的最新的task_id
        self.service_name_pipeline = []
        for service_name in service_name_pipeline: #里面绝对不能含有end
            if service_name == 'end':
                break
            else:
                self.service_name_pipeline.append(service_name)

        self.knob_value_range_dict = copy.copy(knob_value_range_dict)
        self.delay_cons = delay_cons
        self.acc_cons = acc_cons
        self.delay_weight = delay_weight
        self.acc_weight = acc_weight
        self.performance_predictor=IntegratedSafePredictor(kb_path=kb_path,
                                                       service_name_pipeline=service_name_pipeline,
                                                       corrector_param=corrector_param,
                                                       queue_param=queue_param)
        self.default_policy = default_policy
        self.raw_meta_data = raw_meta_data

        self.grope_type_param = grope_type_param
        self.goal_type = goal_type

        # 需要长期保持的流形
        self.dict_str_set_for_MadEye = DictStrSet()
        

    def get_schedule_plan(self, cur_task_id, cur_policy, context_info, grope_type ):

        # 冷启动
        if cur_policy is None or context_info:

            print(cur_policy, context_info)
            print('冷启动')

            new_policy = copy.deepcopy(self.default_policy)

            return new_policy
        
        else:
            print('搜索策略')

            new_policy = cur_policy

            if grope_type == 'MadEye':
                max_queue_size = self.grope_type_param['MadEye']['max_queue_size']
                new_policy = self.get_policy_grope_MadEye(cur_policy = cur_policy,
                                                             context_info = context_info,
                                                             max_queue_size = max_queue_size)

            elif grope_type == 'AdaMEC':
                new_policy = self.get_policy_grope_AdaMEC(cur_policy = cur_policy,
                                                             context_info = context_info)

            elif grope_type == 'Gecko':
                speed_threshold = self.grope_type_param['Gecko']['speed_threshold']
                new_policy = self.get_policy_grope_Gecko(cur_policy = cur_policy,
                                                            context_info = context_info,
                                                            speed_threshold = speed_threshold)
            
            else:
                print('该策略不存在')

            return new_policy
                
    # MadEye的算法: 维系一个固定大小的baseline，每次都从中
    def get_policy_grope_MadEye(self, cur_policy, context_info, max_queue_size):

        print('使用MadEye')

        # (1)首先要获取原本的优先队列的内容。获取后将原本的列表清空。
        cur_value_list = self.dict_str_set_for_MadEye.get_values_copy()
        self.dict_str_set_for_MadEye.delete_all()
        if len(cur_value_list)==0:  #如果初始为空，要加入自己的新元素进去

            # 算出当前策略的分数，然后将其加入到优先队列之中
            dict_obj = copy.deepcopy(cur_policy)
            cur_value_list.append(dict_obj)
        
        # (2)计算这些初始优先队列里每一个元素在新的运行时情境下的分数,并重新放回列表
        for idx in range( len(cur_value_list) ):
            dict_obj = cur_value_list[idx]
            score = self.get_score_of_policy(policy = dict_obj,
                                             context_info = context_info,
                                             grope_type = 'MadEye')
            cur_value_list[idx]['score'] = score
            self.dict_str_set_for_MadEye.add_dict_obj(dict_obj = cur_value_list[idx] )
        
        # (3)进行筛选排序(降序)，并进行筛选，从而得到最新运行时情境下、最佳策略和最佳分数
        self.dict_str_set_for_MadEye.remove_duplication()
        self.dict_str_set_for_MadEye.sort_by_key(key='score',if_dec=True)
        self.dict_str_set_for_MadEye.save_first_num_dict_obj(num = max_queue_size)
        best_dict_obj = self.dict_str_set_for_MadEye.get_first_dict_obj() #必然不为空

        #(4)进入循环, 准备好寻找邻居所依据的配置维度
        knob_list = [knob for knob in self.knob_value_range_dict.keys()]

        while True:

            #(5)获取优先队列中所有元素内容并清空优先队列
            cur_value_list = self.dict_str_set_for_MadEye.get_values_copy()
            self.dict_str_set_for_MadEye.delete_all()

            #(6)对于每一个元素都寻找其邻居，求出分数并加入优先队列
            for idx in range( len(cur_value_list) ):
                dict_obj = cur_value_list[idx]
                neighbor_policies = self.get_neighbors_in_certain_knobs(policy = dict_obj,
                                                                        knob_list = knob_list)
                # 对于每一个邻居求分数,并加入到优先队列中
                for idx2 in range(len(neighbor_policies)):

                    dict_obj2 = neighbor_policies[idx2]
                    score = self.get_score_of_policy(policy = dict_obj2,
                                             context_info = context_info,
                                             grope_type = 'MadEye')
                    neighbor_policies[idx2]['score'] = score
                    self.dict_str_set_for_MadEye.add_dict_obj(dict_obj = neighbor_policies[idx2])
            
            #(7)将原本的列表也完全加入
            for dict_obj in cur_value_list:
                self.dict_str_set_for_MadEye.add_dict_obj(dict_obj=dict_obj)
            
            #(8)重新去重、降序排序、筛选前max_queue_size个点，并判断是否可以更新最优策略，如果可以就返回一个结果
            self.dict_str_set_for_MadEye.remove_duplication()
            self.dict_str_set_for_MadEye.sort_by_key(key='score',if_dec=True)
            self.dict_str_set_for_MadEye.save_first_num_dict_obj(num = max_queue_size)

            temp_best_dict_obj = self.dict_str_set_for_MadEye.get_first_dict_obj()
           
            # 终止循环条件:找不到更优秀的解
            if temp_best_dict_obj is None or temp_best_dict_obj['score'] <= best_dict_obj['score']:
                break
            # 否则更新best_dict_obj并继续下一轮循环
            else:
                best_dict_obj = temp_best_dict_obj

        # 最终返回一个调度策略,删除其中score的部分
        new_policy = best_dict_obj
        del new_policy['score']

        return new_policy

    # AdaMEC的算法：从cur_policy出发持续梯度下降进行寻找。不需要维系一个单独的优先队列状态。
    def get_policy_grope_AdaMEC(self, cur_policy, context_info):
        
        print('使用AdaMEC')
        # (1) 新建一个优先队列
        dict_str_set = DictStrSet()

        # (2) 放入一个初始的元素
        dict_obj = copy.deepcopy(cur_policy)
       
        score = self.get_score_of_policy(policy = dict_obj,
                                         context_info = context_info,
                                         grope_type = 'AdaMEC')
        
        dict_obj['score'] = score
        dict_str_set.add_dict_obj(dict_obj=dict_obj)

        # (3)获得初始最佳策略
        best_dict_obj = dict_obj

        # (4)进入循环
        knob_list = [knob for knob in self.knob_value_range_dict.keys()]
        while True:
            
            # (5)从优先队列中删除并提取一个点，然后将所有的邻居都放入优先队列
            dict_obj = dict_str_set.delete_first_dict_obj()

            if dict_obj is None:
                break

            neighbor_policies = self.get_neighbors_in_certain_knobs(policy = dict_obj,
                                                                    knob_list = knob_list)
            
            for idx2 in range(len(neighbor_policies)):

                dict_obj2 = neighbor_policies[idx2]
                score = self.get_score_of_policy(policy = dict_obj2,
                                            context_info = context_info,
                                            grope_type = 'AdaMEC')
                neighbor_policies[idx2]['score'] = score
                dict_str_set.add_dict_obj(dict_obj = neighbor_policies[idx2])
            
            # (6)进行去重、排序并获取最新点

            dict_str_set.remove_duplication()
            dict_str_set.sort_by_key(key='score', if_dec=True)
            temp_best_dict_obj = dict_str_set.get_first_dict_obj()

            if temp_best_dict_obj is None or temp_best_dict_obj['score'] <= best_dict_obj['score']:
                break
            else:
                best_dict_obj = temp_best_dict_obj
        
        # 最终完成寻找
        new_policy = best_dict_obj
        del new_policy['score']

        return new_policy

    # Gecko的算法：让fps处于AIMD之中。如果目标速度小于阈值，逐步增加帧率；否则帧率减半。
    # 确定了帧率以后，再在剩下的旋钮中寻找能让score最大化的
    def get_policy_grope_Gecko(self, cur_policy, context_info, speed_threshold):

        print('使用Gecko')
        # 首先来确定fps
        cur_fps = cur_policy['fps']
        cur_fps_idx = self.knob_value_range_dict['fps'].index(cur_fps)

        cur_resolution = cur_policy['resolution']
        cur_resolution_idx = self.knob_value_range_dict['resolution'].index(cur_resolution)

        cur_obj_speed = context_info['obj_speed']
        cur_obj_num = context_info['obj_num']

        

        # 根据obj_speed的取值和阈值之间的关系来判断下一个fps应该是多少
        new_fps_idx = cur_fps_idx #初始化
        if 0<cur_obj_speed and cur_obj_speed <= speed_threshold: #速度小，说明变化慢，此时可以降低帧率
            new_fps_idx = int(max( 0, cur_fps_idx / 2.0 ))
            print('fps减半', cur_fps_idx, '便成为',new_fps_idx)
        else:
            new_fps_idx = int(min( len(self.knob_value_range_dict['fps'])-1, cur_fps_idx + 1))
            print('fps增加', cur_fps_idx, '便成为',new_fps_idx)
        
        # 如果obj_num为0，那么就可以降低分辨率了；否则增加分辨率。
        new_resolution_idx = cur_resolution_idx
        if cur_obj_num == 0:
            new_resolution_idx = int(max( 0, cur_resolution_idx / 2.0 ))
        else:
            new_resolution_idx = int(min( len(self.knob_value_range_dict['resolution'])-1, cur_resolution_idx + 1))
        
        
        # 得到新的fps
        new_fps = self.knob_value_range_dict['fps'][new_fps_idx]
        print('fps变化:',cur_fps,'到',new_fps)
        new_resolution = self.knob_value_range_dict['resolution'][new_resolution_idx]

        #以上确保了fps可以足够低。接下来在其他配置维度上继续进行梯度下降

        # (1) 新建一个优先队列
        dict_str_set = DictStrSet()

        # (2) 放入一个初始的元素,并设置其fps为new_fps
        dict_obj = copy.deepcopy(cur_policy)
        dict_obj['fps'] = new_fps
        dict_obj['resolution'] = new_resolution
        score = self.get_score_of_policy(policy = dict_obj,
                                         context_info = context_info,
                                         grope_type = 'Gecko')
        
        dict_obj['score'] = score
        dict_str_set.add_dict_obj(dict_obj=dict_obj)

        # (3)获得初始最佳策略
        best_dict_obj = dict_obj

        # (4)进入循环，但是求邻居的时候不考虑fps的存在，因此解空间小了一个维度
        knob_list = [knob for knob in self.knob_value_range_dict.keys()]
        knob_list.remove('fps')
        knob_list.remove('resolution')
        while True:
            
            # (5)从优先队列中删除并提取一个点，然后将所有的邻居都放入优先队列
            dict_obj = dict_str_set.delete_first_dict_obj()

            if dict_obj is None:
                break

            neighbor_policies = self.get_neighbors_in_certain_knobs(policy = dict_obj,
                                                                    knob_list = knob_list)
            
            for idx2 in range(len(neighbor_policies)):

                dict_obj2 = neighbor_policies[idx2]
                score = self.get_score_of_policy(policy = dict_obj2,
                                            context_info = context_info,
                                            grope_type = 'AdaMEC')
                neighbor_policies[idx2]['score'] = score
                dict_str_set.add_dict_obj(dict_obj = neighbor_policies[idx2])
            
            # (6)进行去重、排序并获取最新点

            dict_str_set.remove_duplication()
            dict_str_set.sort_by_key(key='score', if_dec=True)
            temp_best_dict_obj = dict_str_set.get_first_dict_obj()

            if temp_best_dict_obj is None or temp_best_dict_obj['score'] <= best_dict_obj['score']:
                break
            else:
                best_dict_obj = temp_best_dict_obj
        
        # 最终完成寻找
        new_policy = best_dict_obj
        del new_policy['score']

        return new_policy

    # 计算策略的分数，
    def get_score_of_policy(self, policy, context_info, grope_type):

        # 分数越大越好
        

        delay, acc = self.pre_delay_and_acc(context_info = context_info,
                                            conf_info = policy)
        
        score = 0

        # 分数越大越好


        if self.goal_type == 'prefer':
            #print('当前搜索目标:',self.goal_type)

            delay_loss = 0
            if delay > self.delay_cons:
                delay_loss += ( (delay - self.delay_cons) / self.delay_cons )
            acc_loss = 0
            if acc < self.acc_cons:
                acc_loss += ( (self.acc_cons - acc) / self.acc_cons )

            loss = delay_loss * self.delay_weight + acc_loss * self.acc_weight

            score = max(0, 1-loss)
        
        elif self.goal_type == 'rigid':
            #print('当前搜索目标:',self.goal_type)

            if delay >= self.delay_cons:
                score = 1 - ( (delay - self.delay_cons) / delay )
            else:
                score = 1+acc
        else:
            print('错误。当前搜索目标不对:',self.goal_type)
        return score


    # 预测一个调度策略在当前运行时情境下的时延和精度
    def pre_delay_and_acc(self, context_info, conf_info):

        # 分析时延
        detect_delay = 0
        classify_delay = 0
        trans_delay = 0

        detect_delay = self.performance_predictor.exe_pre_detect(context_info = context_info,
                                                                 conf_info = conf_info,
                                                                 if_correct= False)
        trans_delay = self.performance_predictor.trans_pre(context_info = context_info,
                                                           conf_info = conf_info,
                                                           if_correct = False)
        
        # 如果服务数量大于1，考虑分类时延
        if len(self.service_name_pipeline) > 1:
            classify_delay = self.performance_predictor.exe_pre_classify(context_info = context_info,
                                                                         conf_info = conf_info,
                                                                         if_correct = False)


        delay = detect_delay + trans_delay + classify_delay
        
        acc = self.performance_predictor.acc_pre(context_info = context_info,
                                                 conf_info = conf_info,
                                                 if_correct = False)
        
        return delay, acc

    # 获取一个调度策略在knob_names所指定的一系列配置维度上的邻居
    def get_neighbors_in_certain_knobs(self, policy, knob_list):

        neighbor_policies = []

        # 在每一个配置维度上寻找邻居
        for knob in knob_list:
            cur_knob_value = policy[knob]
            cur_knob_idx = self.knob_value_range_dict[knob].index(cur_knob_value)
            for dir in [-1,1]:
                new_knob_idx = cur_knob_idx + dir
                # 如果新索引在正常范围内，才可以生成新邻居
                if 0 <= new_knob_idx  and  new_knob_idx < len(self.knob_value_range_dict[knob]):
                    new_policy = copy.deepcopy(policy)
                    new_policy[knob] = self.knob_value_range_dict[knob][new_knob_idx]
                    neighbor_policies.append(new_policy)

        # 找到邻居以后，直接返回
        return neighbor_policies







