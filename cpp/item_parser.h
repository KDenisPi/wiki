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

namespace wiki {

using doc_ptr = std::shared_ptr<rapidjson::Document>;
using item_info = std::tuple<std::string, std::string, std::string>;

class ItemParser{
public:
    ItemParser(const int index, std::atomic_int* sync, const std::shared_ptr<char>& buffer)
        : _index(index), _sync(sync), _buffer(buffer) {
    }

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

    inline auto get_sub_name(const doc_ptr& doc, const std::string& name, const std::string& subn) const {
        auto val = doc->FindMember(name.c_str());
        if(val != doc->MemberEnd()){
            auto sval = val->value.FindMember(subn.c_str());
            if(sval != val->value.MemberEnd())
                return std::string(sval->value.GetString());
        }

        return std::string();
    }


    //const rapidjson::Value::ConstValueIterator& it
    item_info parse_item(){
        auto doc = get();

        auto id = get_name(doc, "id");
        auto label = get_sub_name(doc, "label", "en");
        auto descr = get_sub_name(doc, "descriptions", "en");

        return std::make_tuple("", "", "");
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
                auto itm = parse_item();
                if(!std::get<0>(itm).empty()){
                    std::cout << "Index: " << _index << " Item ID: " << std::get<0>(itm) << " Label: " << std::get<1>(itm) << std::endl;
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
    std::atomic_int* _sync;
    doc_ptr ptr_doc;
    int _index = -1;

    std::atomic_bool finish = false;

};

} //namespace
#endif