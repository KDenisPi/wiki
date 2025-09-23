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

    virtual void process(){}

    /**
     * @brief
     *
     * @return const std::shared_ptr<rapidjson::Document>
     */
    const doc_ptr get() {
        return ptr_doc;
    }

    inline auto get_name(const doc_ptr& doc, const std::string& name) const {
        auto val = doc->FindMember(name.c_str());
        return (val == doc->MemberEnd() ? std::string() : std::string(val->value.GetString()));
    }

    inline auto get_str_value(const rapidjson::Value::ConstValueIterator& it, const std::string& name){
        auto val = it->FindMember(name.c_str());
        return (val == it->MemberEnd() ? std::string() : std::string(val->value.GetString()));
    }

    inline auto get_sub_name(const doc_ptr& doc, const std::string& name, const std::string& subn, const std::string& sub2n = "") const {
        auto val = doc->FindMember(name.c_str());
        if(val != doc->MemberEnd()){
            auto sval = val->value.FindMember(subn.c_str());
            if(sval != val->value.MemberEnd())
                if(sval->value.IsString()){
                    return std::string(sval->value.GetString());
                }

                //One more level
                if(!sub2n.empty()){
                    if(sval->value.IsObject())
                    {
                        auto ssval = sval->value.FindMember(sub2n.c_str());
                        if(sval->value.MemberEnd() != ssval && ssval->value.IsString()){
                            return std::string(ssval->value.GetString());
                        }
                    }
                    else if(sval->value.IsArray()){
                        auto ssval = sval->value[0].FindMember(sub2n.c_str());
                        if(sval->value.MemberEnd() != ssval && ssval->value.IsString()){
                            return std::string(ssval->value.GetString());
                        }
                    }
                }
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

    void parse_claim(const rapidjson::Value::ConstMemberIterator& it){
        const auto prop_name = std::string(it->name.GetString());
        if(!_props->is_important_property(prop_name)){
            //std::cout << "Claim not important Property: " << prop_name << std::endl;
            return;
        }

        std::cout << "Claim Important Property: " << prop_name << std::endl;
        return;

        for(auto prop = it->value.MemberBegin(); prop != it->value.MemberEnd(); ++prop){
            const std::string prop_name = std::string(prop->name.GetString());
            std::cout << "Claim Property: " << prop_name << std::endl;
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