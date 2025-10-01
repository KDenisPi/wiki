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

#include "rapidjson/document.h"
#include "prop_dict.h"

namespace wiki {

using doc_ptr = std::shared_ptr<rapidjson::Document>;
using item_info = std::tuple<std::string, std::string, std::string>;

class ItemParser{
public:
    /**
     * @brief Construct a new Item Parser object
     *
     * @param index
     * @param sync
     * @param buffer
     */
    ItemParser(const int index, std::atomic_int* sync, const std::shared_ptr<char>& buffer, const std::shared_ptr<Properties>& props)
        : _index(index), _sync(sync), _buffer(buffer), _props(props) {
    }

    /**
     * @brief Destroy the Item Parser object
     *
     */
    virtual ~ItemParser() {
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
        release(); //not sure

        ptr_doc = std::make_shared<rapidjson::Document>();

        ptr_doc->Parse(buff);
        if(ptr_doc->HasParseError()){
            auto err = ptr_doc->GetParseError();
            std::cout << " Parse error: " << std::to_string(err) << " Offset: " << ptr_doc->GetErrorOffset() << std::endl;

            release();
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
     * @return auto
     */
    inline auto get_str_value(const rapidjson::Value::ConstMemberIterator& it, const std::string& name){
        auto val = it->value.FindMember(name.c_str());
        return (val == it->value.MemberEnd() ? std::string() : std::string(val->value.GetString()));
    }

    inline auto get_str_sub_value(const rapidjson::Value::ConstMemberIterator& val, const std::string& subn, const std::string& sub2n) const{
        auto g_name = [](auto it){return std::string(it->name.GetString());};

        auto sval = val->value.FindMember(subn.c_str());
        if(sval != val->value.MemberEnd()){
            if(sval->value.IsString()){
                return g_name(sval);
            }

            //One more level
            if(!sub2n.empty()){
                if(sval->value.IsObject())
                {
                    auto ssval = sval->value.FindMember(sub2n.c_str());
                    if(sval->value.MemberEnd() != ssval && ssval->value.IsString()){
                        return g_name(ssval);
                    }
                }
                else if(sval->value.IsArray()){
                    auto ssval = sval->value[0].FindMember(sub2n.c_str());
                    if(sval->value.MemberEnd() != ssval && ssval->value.IsString()){
                        return g_name(ssval);
                    }
                }
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
     * @brief Data type for value
     * @parameter "datatype" for value, for example ("wikibase-item", "time")
     * @parameter parameters 2,3 etc depends on datatype
     *
     */
    using data_value = std::tuple<std::string, std::string, std::string>;

    const data_value parse_data_value(const rapidjson::Value::ConstMemberIterator& it, const std::string& prop_name){
        auto datatype = get_str_value(it, s_datatype);
        auto property = get_str_value(it, s_property);

        auto datavalue = it->value.FindMember(s_datavalue.c_str());
        if(it->value.MemberEnd() != datavalue){
            auto value = datavalue->value.FindMember(s_value.c_str());
            if(datavalue->value.MemberEnd() != value){

            }
        }

        std::cout << "Property: " << property << " Data type: " << datatype << std::endl;

        return std::make_tuple("", "", "");
    }

    void print_type(const rapidjson::Value& value, const std::string& label = ""){
        std::cout << label << " Object: " << value.IsObject() << " Array: " << value.IsArray() << " String: " << value.IsString() << std::endl;
    }

    void parse_claim(const rapidjson::Value::ConstMemberIterator& it){
        const auto prop_name = std::string(it->name.GetString());
        if(!_props->is_important_property(prop_name)){
            //std::cout << "Claim not important Property: " << prop_name << std::endl;
            return;
        }

        std::cout << "Claim Important Property: " << prop_name << std::endl;
        //print_type(it->value, "Claim");


        if(it->value.IsArray()){
            const auto property_data = it->value.GetArray();
            for(auto p_data = property_data.Begin(); p_data != property_data.End(); ++p_data){

                //std::cout << " Data Object: " << p_data->IsObject() << " Array: " << p_data->IsArray() << " String: " << p_data->IsString() << std::endl;
                const auto data_obj = p_data->GetObject();
                const auto mainsnak = data_obj.FindMember(s_mainsnak.c_str());
                if(data_obj.MemberEnd() != mainsnak){
                    auto res = parse_data_value(mainsnak, prop_name);
                }
                //break;
            }
        }
    }



    /**
     * @brief
     *
     */
    void worker(){
        std::cout << "Parse started. Index: " << this->_index << std::endl;

        auto fn_no_data = [&]() {
            return (0 == _sync->load());
        };

        for(;;){
            while(!is_finish() && fn_no_data());

            if(is_finish()){
                std::cout << "Finish detected. Index: " << this->_index << std::endl;
                break;
            }

            auto res = load(_buffer.get());
            if(!res){
                std::cout << "Could not parse data. Index: " << this->_index << std::endl;
                //std::cout << _buffer.get() << "|" << std::endl;
            }
            else{
                //Process item information
                auto itm = parse_item();
                if(!std::get<0>(itm).empty()){
                    std::cout << "Index: " << _index << " Item ID: " << std::get<0>(itm) << " Label: " << std::get<1>(itm) << std::endl;
                }

                //Process item claims, one by one
                auto claims = get()->FindMember(s_claims.c_str());
                if(get()->MemberEnd() != claims){
                    for(auto claim = claims->value.MemberBegin(); claim != claims->value.MemberEnd(); ++claim){
                        parse_claim(claim);
                    }
                }
            }

            _sync->store(0);
        }

        std::cout << "Parse finished. Index: " << this->_index << std::endl;
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

    std::atomic_int* _sync;
    doc_ptr ptr_doc;
    int _index = -1;

    std::atomic_bool finish = false;

};

} //namespace
#endif