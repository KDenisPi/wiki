/**
 * @file prop_dict.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-12
 *
 * @copyright Copyright (c) 2025
 *
 */
#ifndef WIKI_PROPDICT_H_
#define WIKI_PROPDICT_H_


#include <string>
#include <tuple>
#include <vector>
#include <algorithm>
#include <memory>

#include "rapidjson/document.h"

#include "defines.h"

namespace wiki {

class Properties{
public:
    Properties() {
        ptr_prop = std::make_shared<rapidjson::Document>();
        buffer = std::shared_ptr<char>(new char[2*1024*1024]); //properties.json - 1.4Mb
    }

    /**
     * @brief Destroy the Properties object
     *
     */
    virtual ~Properties() {
        if(ptr_prop)
            ptr_prop.reset();
    }

    bool load(const std::string& filename);

    /**
     * @brief
     *
     * @return true
     * @return false
     */
    inline bool is_loaded() const {
        return (ptr_prop ? loaded : false);
    }

    /**
     * @brief
     *
     * @param prop_id
     * @return const p_info&
     */
    const pInfo get_prop(const pID& prop_id) const;

    /**
     * @brief
     *
     * @param v_props
     */
    void load_important_property(std::vector<pID> v_props){
        prop_important.swap(v_props);
        std::sort(prop_important.begin(), prop_important.end());
    }

    /**
     * @brief
     *
     * @param v_props
     */
    void load_instance_of_property(std::vector<pID> v_props){
        prop_P31.swap(v_props);
        std::sort(prop_P31.begin(), prop_P31.end());
    }


    /**
     * @brief
     *
     * @param prop_id
     * @return true
     * @return false
     */
    bool is_important_property(const pID& prop_id) const {
        return (std::find(prop_important.begin(), prop_important.end(), prop_id) != prop_important.end());
    }

    bool is_useful_instance_of_value(const pID& prop_id) const {
        return (std::find(prop_P31.begin(), prop_P31.end(), prop_id) != prop_P31.end());
    }

    /**
     * @brief
     *
     * @return size_t
     */
    size_t MemberCount() const {
        return (is_loaded() ? ptr_prop->MemberCount() : 0);
    }

    /**
     * @brief
     *
     * @return * const std::shared_ptr<rapidjson::Document>
     */
    const std::shared_ptr<rapidjson::Document> get(){
        return ptr_prop;
    }

protected:
    bool loaded = false;
    std::shared_ptr<char> buffer; // Declare a character array (buffer) to store the line

    std::shared_ptr<rapidjson::Document> ptr_prop;
    std::vector<pID> prop_important;
    std::vector<pID> prop_P31;  //Good values for instance of properties
};

}//namespace wiki

#endif