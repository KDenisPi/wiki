/**
 * @file item_parser.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-13
 *
 * @copyright Copyright (c) 2025
 *
 */

#ifndef WIKI_ITEM_PARSER_H_
#define WIKI_ITEM_PARSER_H_

#include <memory>
#include <atomic>
#include <chrono>
#include <tuple>
#include <fstream>
#include <string>
#include <vector>

#include "rapidjson/document.h"

#include "defines.h"
#include "prop_dict.h"
#include "receiver.h"

namespace wiki {

using doc_ptr = std::shared_ptr<rapidjson::Document>;

/**
 * @brief
 * 0 - property ID
 * 1 - key value for this data item
 * 2 - type of key value
 * 3 - additional parameter
 */
using data_value = std::tuple<std::string, std::string, std::string, std::string>;


class ItemParser{
public:
    /**
     * @brief Construct a new Item Parser object
     *
     * @param index
     * @param sync
     * @param buffer
     */
    ItemParser(const int index,
        std::atomic_int* sync,
        const std::shared_ptr<char>& buffer,
        const std::shared_ptr<Properties>& props,
        const std::shared_ptr<Receiver>& receiver
    )
        : _index(index), _sync(sync), _buffer(buffer), _props(props), _receiver(receiver) {

        const std::string f_name = "iparser_" + std::to_string(index) + ".log";
        logFile.open(f_name, std::ios::out | std::ios::app);
        if(logFile.is_open()){
            logFile.seekg(0, std::fstream::end);
        }
    }

    /**
     * @brief Destroy the Item Parser object
     *
     */
    virtual ~ItemParser() {
        if(logFile.is_open()){
            logFile.close();
        }

        release();
    }

    /**
     * @brief
     *
     * @param buff
     * @return true
     * @return false
     */
    bool load(const char* buff){

        //Release JSON object (?)
        release();

        ptr_doc = std::make_shared<rapidjson::Document>();
        ptr_doc->Parse(buff);
        if(ptr_doc->HasParseError()){
            char msg_buff[40];
            auto err = ptr_doc->GetParseError();
            std::string msg = "Parse error: " + std::to_string(err) + " Offset: " + std::to_string(ptr_doc->GetErrorOffset());

            if( strlen(buff) >= sizeof(msg_buff))
                std::strncpy(msg_buff, buff, sizeof(msg_buff));
            else
                std::strncpy(msg_buff, buff, strlen(buff));

            log(msg + "[" + std::string(msg_buff) + "]");
            return false;
        }
        return true;
    }

    /**
     * @brief
     *
     */
    inline void release(){
        if(ptr_doc){
            ptr_doc.reset();
        }
    }

    /**
     * @brief
     *
     * @param str
     */
    void log(const std::string& str){
        if(logFile.is_open()){
            logFile << str << std::endl;
        }
    }

    const std::string s_id = "id";
    const std::string s_label = "labels";
    const std::string s_descr = "descriptions";
    const std::string s_lng_en = "en";
    const std::string s_claims = "claims";
    const std::string s_value = "value";
    const std::string s_property = "property";

    const std::string s_mainsnak = "mainsnak";
    const std::string s_snaktype = "snaktype";
    const std::string s_datatype = "datatype";
    const std::string s_datavalue = "datavalue";
    const std::string s_type = "type";
    const std::string s_entity_type = "entity-type";
    const std::string s_time = "time";
    const std::string s_tmz = "timezone";

    const std::string s_qualifiers = "qualifiers";
    const std::string s_qualifiers_order = "qualifiers-order";

    const std::string s_P31 = "P31"; //"Instance of" property

    /**
     * @brief
     *
     */
    virtual void process(){}

    /**
     * @brief
     *
     * @return const std::shared_ptr<rapidjson::Document>
     */
    const doc_ptr get() {
        return ptr_doc;
    }

    /**
     * @brief Get the name object
     *
     * @param doc
     * @param name
     * @return auto
     */
    inline auto get_name(const doc_ptr& doc, const std::string& name) const {
        auto val = doc->FindMember(name.c_str());
        return (val == doc->MemberEnd() ? std::string() : std::string(val->value.GetString()));
    }

    /**
     * @brief Get the str value object
     *
     * @param it
     * @param name
     * @return const auto
     */
     inline const auto get_str_value(const rapidjson::Value::ConstMemberIterator& it, const std::string& name){
        auto val = it->value.FindMember(name.c_str());
        return (val == it->value.MemberEnd() ? std::string() : std::string(val->value.GetString()));
    }

    /**
     * @brief Get the obj str value object
     *
     * @param obj
     * @param name
     * @return const auto
     */
    inline const auto get_obj_str_value(const rapidjson::Value::ConstObject& obj, const std::string& name){
        const auto item = obj.FindMember(name.c_str());
        return (obj.MemberEnd() == item ? std::string() : std::string(item->value.GetString()));
    }

    /**
     * @brief Get the number value object
     *
     * @tparam T
     * @param it
     * @param name
     * @return T
     */
    template <typename T>
    inline T get_number_value(const rapidjson::Value::ConstMemberIterator& it, const std::string& name){
        auto val = it->value.FindMember(name.c_str());
        if( val == it->value.MemberEnd() ){
            return (T)0;
        }
        if(val->value.IsInt()){
            return val->value.GetInt();
        }
        if(val->value.IsFloat()){
            return val->value.GetFloat();
        }
        if(val->value.IsInt64()){
            return (T)val->value.GetInt64();
        }

        return (T)0;
    }

    /**
     * @brief
     *
     * @param obj
     * @return const data_value
     */
    const data_value parse_qualifiers(const rapidjson::Value::ConstObject& obj){
        //P4649;identity of subject in context
        //P805;statement is subject of;(qualifying) item that describes the relation identified in this statement
        std::vector<std::string> q_props = {"P4649", "P805"};

        const auto q_order = obj.FindMember(s_qualifiers_order.c_str());
        if(obj.MemberEnd() != q_order){
            //print_type(q_order->value);
            const auto q_order_ar = q_order->value.GetArray();
            for(auto q_data = q_order_ar.Begin(); q_data != q_order_ar.End(); ++q_data){
                const auto q_val = q_data->GetString();
                for(auto p : q_props){
                    if(p == q_val){
                        const auto q_qualifs = obj.FindMember(s_qualifiers.c_str());
                        if(obj.MemberEnd() != q_qualifs){
                            const auto qual_arry = q_qualifs->value.FindMember(p.c_str());    //get PXXX array
                            const auto qual_first = qual_arry->value[0].GetObject();
                            auto res = pasrse_obj_data_value(qual_first);

                            std::cout << "Q P: " << q_val << " Val: " << std::get<1>(res) << std::endl;
                            if(!std::get<2>(res).empty()){
                                return res;
                            }
                        }
                    }
                }
            }
        }

        return std::make_tuple("", "", "", "");
    }

    /**
     * @brief
     *
     * @tparam T
     * @param it
     * @param pname
     * @param result
     * @return const int
     */
    template <typename T>
    const int parse_property(const rapidjson::Value::ConstMemberIterator& it, const std::string& pname, std::vector<T>& result){
        if(it->value.IsArray()){
            const auto property_data = it->value.GetArray();
            for(auto p_data = property_data.Begin(); p_data != property_data.End(); ++p_data){
                const auto data_obj = p_data->GetObject();
                const auto mainsnak = data_obj.FindMember(s_mainsnak.c_str());
                if(data_obj.MemberEnd() != mainsnak){
                    auto res = parse_data_value(mainsnak, pname);
                    if(!std::get<0>(res).empty()){
                        //std::cout << "parse_property PP:" << pname << std::endl;
                        //there id date/time - try to find qualifiers
                        if(is_type_time(std::get<2>(res))){
                            const auto q_val = parse_qualifiers(data_obj);
                            if(!std::get<1>(q_val).empty()){
                                res = std::make_tuple(std::get<0>(res), std::get<1>(res), std::get<2>(res), std::get<1>(q_val));
                            }
                        }

                        result.push_back(pack<T>(res));
                    }
                }
            }
        }

        return result.size();
    }

    /**
     * @brief
     *
     * @tparam T
     * @param data
     * @return const T
     */
    template <typename T>
    const T pack(const data_value& data);

    /**
     * @brief Get the str sub value object
     *
     * @param val
     * @param subn
     * @param sub2n
     * @return auto
     */
    inline auto get_str_sub_value(const rapidjson::Value::ConstMemberIterator& val, const std::string& subn, const std::string& sub2n) const{
        auto g_name = [](auto it){return (it->value.IsString() ? std::string(it->value.GetString()) : std::string());};

        auto sval = val->value.FindMember(subn.c_str());
        if(sval != val->value.MemberEnd()){
            //One more level
            if(!sub2n.empty()){
                if(sval->value.IsObject())
                {
                    auto ssval = sval->value.FindMember(sub2n.c_str());
                    if(sval->value.MemberEnd() != ssval){
                        return g_name(ssval);
                    }
                }
                else if(sval->value.IsArray()){
                    auto ssval = sval->value[0].FindMember(sub2n.c_str());
                    if(sval->value.MemberEnd() != ssval){
                        return g_name(ssval);
                    }
                }
            }
            else{
                return g_name(sval);
            }
        }
        return std::string();
    }

    /**
     * @brief Get the sub name object
     *
     * @param doc
     * @param name
     * @param subn
     * @param sub2n
     * @return auto
     */
    inline auto get_sub_name(const doc_ptr& doc, const std::string& name, const std::string& subn, const std::string& sub2n = "") const {

        auto val = doc->FindMember(name.c_str());
        if(val != doc->MemberEnd()){
            return get_str_sub_value(val, subn, sub2n);
        }

        return std::string();
    }

    /**
     * @brief
     *
     * @return item_info
     */
    item_info parse_item(){
        auto doc = get();

        const auto id = get_name(doc, s_id);
        const auto label = get_sub_name(doc, s_label, s_lng_en, s_value);
        const auto descr = get_sub_name(doc, s_descr, s_lng_en, s_value);

        return std::make_tuple(id, label, descr);
    }

    /**
     * @brief
     *
     * @param dtype
     * @return true
     * @return false
     */
    inline const bool is_type_wikiid(const std::string& dtype) const {
        return (dtype == "wikibase-entityid");
    }

    inline const bool is_type_time(const std::string& dtype) const {
        return (dtype == s_time);
    }

    /**
     * @brief
     *
     * @param it
     * @param prop_name
     * @return const data_value
     */
    data_value parse_data_value(const rapidjson::Value::ConstMemberIterator& it, const std::string& prop_name = ""){
        auto datatype = get_str_value(it, s_datatype);
        auto property = get_str_value(it, s_property);

        //We are interesting only for properties with specisfied name if it set
        if(!prop_name.empty() && (property != prop_name)){
            return std::make_tuple("", "", "", "");
        }

        std::string key_value;
        auto datavalue = it->value.FindMember(s_datavalue.c_str());
        if(it->value.MemberEnd() != datavalue){
            const auto dtype = get_str_value(datavalue, s_type);
            auto value = datavalue->value.FindMember(s_value.c_str());
            if(datavalue->value.MemberEnd() != value){
                if(is_type_wikiid(dtype)){
                    key_value = get_str_value(value, s_id);
                    return std::make_tuple(property, key_value, dtype, "");
                }
                else if(is_type_time(dtype)){
                    key_value = get_str_value(value, s_time);
                    auto dmz = get_number_value<int>(value, s_tmz);
                    return std::make_tuple(property, key_value, dtype, std::to_string(dmz));
                }
            }
        }

        return std::make_tuple("", "", "", "");
    }


    /**
     * @brief
     *
     * @param obj
     * @param prop_name
     * @return const data_value
     */
    data_value pasrse_obj_data_value(const rapidjson::Value::ConstObject& obj, const std::string& prop_name = ""){
        auto datatype = get_obj_str_value(obj, s_datatype);
        auto property = get_obj_str_value(obj, s_property);

        //We are interesting only for properties with specisfied name if it set
        if(!prop_name.empty() && (property != prop_name)){
            return std::make_tuple("", "", "", "");
        }

        std::string key_value;
        auto datavalue = obj.FindMember(s_datavalue.c_str());
        if(obj.MemberEnd() != datavalue){
            const auto dtype = get_str_value(datavalue, s_type);
            auto value = datavalue->value.FindMember(s_value.c_str());
            if(datavalue->value.MemberEnd() != value){
                if(is_type_wikiid(dtype)){
                    key_value = get_str_value(value, s_id);
                    return std::make_tuple(property, key_value, dtype, "");
                }
                else if(is_type_time(dtype)){
                    key_value = get_str_value(value, s_time);
                    auto dmz = get_number_value<int>(value, s_tmz);
                    return std::make_tuple(property, key_value, dtype, std::to_string(dmz));
                }
            }
        }

        return std::make_tuple("", "", "", "");

    }

    /**
     * @brief
     *
     * @param value
     * @param label
     */
    void print_type(const rapidjson::Value& value, const std::string& label = ""){
        std::cout << label << " Object: " << value.IsObject() << " Array: " << value.IsArray() << " String: " << value.IsString() << std::endl;
    }

    /**
     * @brief Get the instance of object
     *
     * @param it
     * @param vinsts
     * @return const int
     */
    const int get_instance_of(const rapidjson::Value::ConstMemberIterator& it, prop_ids& vinsts){
        auto res = parse_property<std::string>(it, s_P31, vinsts);
        return res;
    }

    /**
     * @brief
     *
     * @param it
     */
    void parse_claim(const rapidjson::Value::ConstMemberIterator& it){
        const auto prop_name = std::string(it->name.GetString());
        if(!_props->is_important_property(prop_name)){
            return;
        }

        std::vector<data_value> result;
        const auto r_count = parse_property<data_value>(it, prop_name, result);
        std::cout << "Property: " << prop_name << " Items:" << r_count << std::endl;
        for(data_value res : result){
            std::cout << "0:" << std::get<0>(res) << " 1:" << std::get<1>(res) << " 2:" << std::get<2>(res) << " 3:" << std::get<3>(res) << std::endl;
            /*
            if(_receiver){
                _receiver->put_dictionary_value(std::get<0>(res), std::get<1>(res), std::pair(std::get<2>(res), std::get<3>(res)));
            }
            */
        }
    }



    /**
     * @brief
     *
     */
    void worker(){
        //std::cout << "Parse started. Index: " << this->_index << std::endl;

        auto fn_no_data = [&]() {
            return (0 == _sync->load());
        };

        for(;;){
            while(!is_finish() && fn_no_data());

            if(is_finish()){
                //std::cout << "Finish detected. Index: " << this->_index << std::endl;
                break;
            }

            auto res = load(_buffer.get());
            if(res){
                //Process item information
                auto itm = parse_item();
                if( !std::get<0>(itm).empty() ){
                    if(_receiver){
                        _receiver->put_dictionary_value("Item", std::get<0>(itm), std::pair(std::get<1>(itm),std::get<2>(itm)));
                    }
                }

                //Process item claims, one by one
                auto claims = get()->FindMember(s_claims.c_str());
                if( get()->MemberEnd() != claims ){
                    //Detect "Instance of" property for this Item
                    auto p31 = claims->value.FindMember(s_P31.c_str());
                    if( claims->value.MemberEnd() != p31){
                        prop_ids pids;
                        auto insts = get_instance_of(p31, pids);

                        for( auto claim = claims->value.MemberBegin(); claim != claims->value.MemberEnd(); ++claim ){
                            parse_claim(claim);
                        }
                    }

                }
            }

            _sync->store(0);
        }

        //std::cout << "Parse finished. Index: " << this->_index << std::endl;
    }



    /**
     * @brief Set the finish object
     *
     * @return * void
     */
    void set_finish(){
        finish = true;
    }

    /**
     * @brief
     *
     * @return true
     * @return false
     */
    inline const bool is_finish(){
        return finish.load();
    }

private:
    std::shared_ptr<char> _buffer;
    std::shared_ptr<Properties> _props;
    std::shared_ptr<Receiver> _receiver;

    std::atomic_int* _sync;

    doc_ptr ptr_doc;
    int _index = -1;

    std::atomic_bool finish = false;

    std::fstream logFile;
};


} //namespace
#endif